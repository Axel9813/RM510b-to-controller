package com.dji.rc_to_controller

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.util.Log

/**
 * Reads 9-byte frames from a Raspberry Pi Pico running MicroPython
 * over USB CDC serial.
 *
 * Frame format: [0xAA] [core_lo] [core_hi] [extra_lo] [extra_hi]
 *                      [joy_x_lo] [joy_x_hi] [joy_y_lo] [joy_y_hi]
 *
 * Handles two Pico states:
 *   PID 0x0003 — RP2 Boot (BOOTSEL mode): sends PICOBOOT reboot command
 *                to force the Pico into application (MicroPython) mode.
 *   PID 0x0005+ — MicroPython CDC: claims the CDC Data interface (class 0x0A)
 *                 and reads frames from its bulk IN endpoint.
 */
class PicoUsbReader(
    private val usbManager: UsbManager,
    private val onFrame: (IntArray) -> Unit,
    private val onError: (String) -> Unit
) {
    companion object {
        private const val TAG = "PicoUsbReader"
        private const val VID = 0x2E8A          // Raspberry Pi
        private const val PID_BOOTSEL = 0x0003  // RP2 Boot (BOOTSEL mode)
        private const val SYNC_BYTE = 0xAA
        private const val FRAME_SIZE = 9  // 1 sync + 2 core + 2 extra + 2 joyX + 2 joyY
        private const val READ_TIMEOUT_MS = 100
        private const val DISCONNECT_THRESHOLD = 50 // consecutive -1 reads → treat as disconnected (~5s)
    }

    @Volatile
    private var running = false
    private var thread: Thread? = null
    private var connection: UsbDeviceConnection? = null
    private var usbInterface: UsbInterface? = null

    val isRunning: Boolean get() = running

    fun findDevice(): UsbDevice? {
        for (device in usbManager.deviceList.values) {
            Log.d(TAG, "USB device on bus: VID=${device.vendorId.toString(16)} " +
                    "PID=${device.productId.toString(16)} name=${device.deviceName} " +
                    "ifaces=${device.interfaceCount}")
        }
        return usbManager.deviceList.values.firstOrNull { device ->
            device.vendorId == VID
        }
    }

    /**
     * Check if the Pico is in BOOTSEL (boot ROM) mode.
     */
    fun isBootselMode(device: UsbDevice): Boolean {
        return device.vendorId == VID && device.productId == PID_BOOTSEL
    }

    /**
     * Send PICOBOOT reboot command to exit BOOTSEL mode.
     *
     * The RP2040 boot ROM exposes a vendor-specific interface (class 0xFF)
     * called PICOBOOT. Commands are sent as 32-byte structures via the
     * bulk OUT endpoint. We send a REBOOT command (0x02) to make the Pico
     * boot into the flashed application (MicroPython).
     *
     * Returns true if the command was sent successfully.
     */
    fun rebootFromBootsel(device: UsbDevice): Boolean {
        if (!usbManager.hasPermission(device)) {
            Log.w(TAG, "No permission to reboot Pico from BOOTSEL")
            return false
        }

        // Find the PICOBOOT vendor interface (class 0xFF)
        var picobootIface: UsbInterface? = null
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (iface.interfaceClass == UsbConstants.USB_CLASS_VENDOR_SPEC) {
                picobootIface = iface
                break
            }
        }
        if (picobootIface == null) {
            Log.w(TAG, "No PICOBOOT interface found on BOOTSEL device")
            return false
        }

        val outEp = findBulkOutEndpoint(picobootIface)
        if (outEp == null) {
            Log.w(TAG, "No bulk OUT endpoint on PICOBOOT interface")
            return false
        }

        val conn = usbManager.openDevice(device) ?: run {
            Log.e(TAG, "Failed to open BOOTSEL device")
            return false
        }

        try {
            conn.claimInterface(picobootIface, true)

            val inEp = findBulkInEndpoint(picobootIface)

            // Helper: build a 32-byte PICOBOOT command
            fun makeCmd(cmdId: Int, cmdSize: Int, token: Int): ByteArray {
                val cmd = ByteArray(32)
                cmd[0] = 0x0b; cmd[1] = 0xd1.toByte(); cmd[2] = 0x1f; cmd[3] = 0x43 // magic
                cmd[4] = (token and 0xFF).toByte() // dToken
                cmd[8] = cmdId.toByte()            // bCmdId
                cmd[9] = cmdSize.toByte()          // bCmdSize
                return cmd
            }

            // Helper: send command and read ACK (PICOBOOT requires reading status after each cmd)
            fun sendCmd(cmd: ByteArray, label: String): Boolean {
                val sent = conn.bulkTransfer(outEp, cmd, cmd.size, 2000)
                Log.d(TAG, "PICOBOOT: $label OUT=$sent bytes")
                if (inEp != null) {
                    val ack = ByteArray(24)
                    val ackLen = conn.bulkTransfer(inEp, ack, ack.size, 2000)
                    Log.d(TAG, "PICOBOOT: $label ACK=$ackLen bytes")
                }
                return sent == cmd.size
            }

            // Step 1: EXCLUSIVE_ACCESS (cmdId=0x01) — required before reboot
            val excl = makeCmd(0x01, 1, 1)
            excl[16] = 0x01  // bExclusive = true
            sendCmd(excl, "EXCLUSIVE_ACCESS")

            // Step 2: REBOOT (cmdId=0x02, cmdSize=0x0c)
            val reboot = makeCmd(0x02, 0x0c, 2)
            // dPC = 0, dSP = 0 (bytes 16-23 already zero = boot from flash)
            // dDelay = 500ms (bytes 24-27, little-endian)
            reboot[24] = 0xF4.toByte()
            reboot[25] = 0x01
            val ok = sendCmd(reboot, "REBOOT")

            Log.i(TAG, "PICOBOOT: reboot sequence complete (sent=$ok)")
            return ok
        } catch (e: Exception) {
            Log.e(TAG, "PICOBOOT reboot failed: ${e.message}")
            return false
        } finally {
            try {
                conn.releaseInterface(picobootIface)
                conn.close()
            } catch (_: Exception) {}
        }
    }

    fun start(): Boolean {
        if (running) return true

        val device = findDevice()
        if (device == null) {
            onError("Pico not found (VID:${VID.toString(16)})")
            return false
        }

        // If Pico is in BOOTSEL mode, we can't read CDC data.
        // Return a specific error so PicoPlugin can handle it.
        if (isBootselMode(device)) {
            onError("Pico is in BOOTSEL mode (PID:0003) — not running MicroPython")
            return false
        }

        if (!usbManager.hasPermission(device)) {
            onError("No USB permission for Pico")
            return false
        }

        // Log all interfaces for diagnostics
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            Log.d(TAG, "  Interface $i: class=0x${iface.interfaceClass.toString(16)} " +
                    "subclass=0x${iface.interfaceSubclass.toString(16)} " +
                    "endpoints=${iface.endpointCount}")
        }

        // Find the CDC Data interface (class 0x0A).
        val dataIface = findCdcDataInterface(device)
        if (dataIface == null) {
            onError("No CDC Data interface found on Pico")
            return false
        }

        val inEndpoint = findBulkInEndpoint(dataIface)
        if (inEndpoint == null) {
            onError("No bulk IN endpoint found on CDC Data interface")
            return false
        }

        val conn = usbManager.openDevice(device)
        if (conn == null) {
            onError("Failed to open Pico USB device")
            return false
        }

        if (!conn.claimInterface(dataIface, true)) {
            conn.close()
            onError("Failed to claim CDC Data interface")
            return false
        }

        // CDC ACM: enable DTR/RTS
        val ctrlIface = findCdcControlInterface(device)
        if (ctrlIface != null) {
            conn.claimInterface(ctrlIface, true)
            conn.controlTransfer(0x21, 0x22, 0x03, ctrlIface.id, null, 0, 100)
        }

        // Send Ctrl+C + Ctrl+D to ensure main.py starts (in case of REPL mode)
        val outEndpoint = findBulkOutEndpoint(dataIface)
        if (outEndpoint != null) {
            val reset = byteArrayOf(0x03, 0x03, 0x04)
            val sent = conn.bulkTransfer(outEndpoint, reset, reset.size, 500)
            Log.i(TAG, "Sent soft-reboot sequence ($sent bytes)")
            Thread.sleep(2000)
        }

        connection = conn
        usbInterface = dataIface
        running = true

        val bufSize = maxOf(inEndpoint.maxPacketSize, 64)
        Log.i(TAG, "Endpoint maxPacketSize=${inEndpoint.maxPacketSize}, starting read thread")

        thread = Thread({
            Log.i(TAG, "Read thread started")
            val buffer = ByteArray(bufSize)
            val ring = ByteArray(256)
            var ringLen = 0
            var readCount = 0
            var consecutiveErrors = 0
            var lastLogTime = System.currentTimeMillis()

            while (running) {
                val bytesRead = conn.bulkTransfer(inEndpoint, buffer, bufSize, READ_TIMEOUT_MS)
                readCount++

                val now = System.currentTimeMillis()
                if (now - lastLogTime > 3000) {
                    Log.d(TAG, "bulkTransfer stats: reads=$readCount, lastResult=$bytesRead, ringLen=$ringLen")
                    if (bytesRead > 0) {
                        val hex = buffer.take(minOf(bytesRead, 16)).joinToString(" ") {
                            "%02X".format(it.toInt() and 0xFF)
                        }
                        Log.d(TAG, "raw data ($bytesRead bytes): $hex")
                    }
                    readCount = 0
                    lastLogTime = now
                }

                if (bytesRead < 0) {
                    consecutiveErrors++
                    if (consecutiveErrors >= DISCONNECT_THRESHOLD) {
                        Log.e(TAG, "USB disconnected ($consecutiveErrors consecutive read failures)")
                        onError("Pico USB disconnected")
                        running = false
                        break
                    }
                } else {
                    consecutiveErrors = 0
                }

                if (bytesRead > 0) {
                    val space = ring.size - ringLen
                    val toCopy = minOf(bytesRead, space)
                    System.arraycopy(buffer, 0, ring, ringLen, toCopy)
                    ringLen += toCopy

                    var i = 0
                    while (i + FRAME_SIZE - 1 < ringLen) {
                        if ((ring[i].toInt() and 0xFF) == SYNC_BYTE) {
                            val coreLo = ring[i + 1].toInt() and 0xFF
                            val coreHi = ring[i + 2].toInt() and 0xFF
                            val extraLo = ring[i + 3].toInt() and 0xFF
                            val extraHi = ring[i + 4].toInt() and 0xFF
                            val joyXLo = ring[i + 5].toInt() and 0xFF
                            val joyXHi = ring[i + 6].toInt() and 0xFF
                            val joyYLo = ring[i + 7].toInt() and 0xFF
                            val joyYHi = ring[i + 8].toInt() and 0xFF
                            val frame = intArrayOf(
                                coreLo or (coreHi shl 8),
                                extraLo or (extraHi shl 8),
                                joyXLo or (joyXHi shl 8),
                                joyYLo or (joyYHi shl 8)
                            )
                            onFrame(frame)
                            i += FRAME_SIZE
                        } else {
                            i++
                        }
                    }

                    if (i > 0 && i < ringLen) {
                        System.arraycopy(ring, i, ring, 0, ringLen - i)
                    }
                    ringLen -= i
                }
            }
            Log.i(TAG, "Read thread stopped")
        }, "PicoUsbReader")
        thread!!.start()

        return true
    }

    fun stop() {
        running = false
        thread?.join(500)
        thread = null
        connection?.let { conn ->
            usbInterface?.let { conn.releaseInterface(it) }
            conn.close()
        }
        connection = null
        usbInterface = null
    }

    // ── Streaming monitor mode ──────────────────────────────────────────────────

    @Volatile
    private var monitoring = false
    private var monitorThread: Thread? = null
    private var monitorConn: UsbDeviceConnection? = null
    private var monitorOutEp: UsbEndpoint? = null
    private var monitorDataIface: UsbInterface? = null
    private var monitorCtrlIface: UsbInterface? = null

    val isMonitoring: Boolean get() = monitoring

    /**
     * Enter raw REPL, execute [code], and stream stdout lines to [onLine] in real-time.
     * Blocks until [stopStreamingExec] is called or the code terminates.
     * Must be called on a background thread. Reader must be stopped first.
     */
    fun startStreamingExec(code: String, onLine: (String) -> Unit): Boolean {
        if (monitoring) return false

        val device = findDevice() ?: return false
        if (isBootselMode(device)) return false
        if (!usbManager.hasPermission(device)) return false

        val dataIface = findCdcDataInterface(device) ?: return false
        val outEp = findBulkOutEndpoint(dataIface) ?: return false
        val inEp = findBulkInEndpoint(dataIface) ?: return false

        val conn = usbManager.openDevice(device) ?: return false
        conn.claimInterface(dataIface, true)

        val ctrlIface = findCdcControlInterface(device)
        if (ctrlIface != null) {
            conn.claimInterface(ctrlIface, true)
            conn.controlTransfer(0x21, 0x22, 0x03, ctrlIface.id, null, 0, 100)
        }

        monitorConn = conn
        monitorOutEp = outEp
        monitorDataIface = dataIface
        monitorCtrlIface = ctrlIface

        if (!enterRawRepl(conn, outEp, inEp)) {
            Log.e(TAG, "Monitor: failed to enter raw REPL")
            conn.releaseInterface(dataIface)
            ctrlIface?.let { conn.releaseInterface(it) }
            conn.close()
            monitorConn = null
            return false
        }

        // Send code + Ctrl+D to execute
        sendBytes(conn, outEp, code.toByteArray())
        sendBytes(conn, outEp, byteArrayOf(0x04))

        monitoring = true
        monitorThread = Thread({
            Log.i(TAG, "Monitor read loop started")
            val buf = ByteArray(512)
            val lineBuf = StringBuilder()

            while (monitoring) {
                val n = conn.bulkTransfer(inEp, buf, buf.size, 200)
                if (n > 0) {
                    for (i in 0 until n) {
                        val c = buf[i].toInt() and 0xFF
                        if (c == 0x04) {
                            // End-of-output marker — code finished or was interrupted
                            monitoring = false
                            break
                        }
                        if (c == '\n'.code) {
                            val line = lineBuf.toString()
                            lineBuf.clear()
                            if (line.isNotEmpty() && line != "OK") {
                                onLine(line)
                            }
                        } else if (c != '\r'.code) {
                            lineBuf.append(c.toChar())
                        }
                    }
                }
            }
            Log.i(TAG, "Monitor read loop ended")
        }, "PicoMonitor")
        monitorThread!!.start()

        return true
    }

    /**
     * Stop the streaming monitor: interrupt running code, exit raw REPL,
     * soft-reboot the Pico, and close the USB connection.
     */
    fun stopStreamingExec() {
        if (!monitoring && monitorThread == null) return
        monitoring = false

        val conn = monitorConn
        val outEp = monitorOutEp
        val dataIface = monitorDataIface
        val ctrlIface = monitorCtrlIface

        // Send Ctrl+C to interrupt running code
        if (conn != null && outEp != null) {
            try {
                sendBytes(conn, outEp, byteArrayOf(0x03, 0x03))
            } catch (_: Exception) {}
        }

        monitorThread?.join(2000)
        monitorThread = null

        // Exit raw REPL and soft-reboot
        if (conn != null && outEp != null && dataIface != null) {
            try {
                val inEp = findBulkInEndpoint(dataIface)
                if (inEp != null) {
                    exitRawRepl(conn, outEp, inEp, true)
                }
            } catch (_: Exception) {}
            try {
                conn.releaseInterface(dataIface)
                ctrlIface?.let { conn.releaseInterface(it) }
                conn.close()
            } catch (_: Exception) {}
        }

        monitorConn = null
        monitorOutEp = null
        monitorDataIface = null
        monitorCtrlIface = null
    }

    // ── Raw REPL file upload & code execution ────────────────────────────────

    /**
     * Upload a file to the Pico's filesystem via raw REPL.
     *
     * Protocol (same as mpremote/ampy):
     *   1. Ctrl+C (interrupt running program)
     *   2. Ctrl+A (enter raw REPL — no echo, delimited output)
     *   3. Send Python code to write file
     *   4. Ctrl+D (execute)
     *   5. Read response (OK + output + OK, or error)
     *   6. Ctrl+B (exit raw REPL back to normal REPL)
     *   7. Ctrl+D (soft-reboot → runs main.py)
     *
     * Must be called while the reader is STOPPED.
     * Returns: result message (success/error)
     */
    fun uploadFile(filename: String, content: ByteArray): String {
        val device = findDevice() ?: return "Pico not found"
        if (isBootselMode(device)) return "Pico is in BOOTSEL mode"
        if (!usbManager.hasPermission(device)) return "No USB permission"

        val dataIface = findCdcDataInterface(device) ?: return "No CDC Data interface"
        val outEp = findBulkOutEndpoint(dataIface) ?: return "No bulk OUT endpoint"
        val inEp = findBulkInEndpoint(dataIface) ?: return "No bulk IN endpoint"

        val conn = usbManager.openDevice(device) ?: return "Failed to open device"
        conn.claimInterface(dataIface, true)

        // Claim control interface for DTR/RTS
        val ctrlIface = findCdcControlInterface(device)
        if (ctrlIface != null) {
            conn.claimInterface(ctrlIface, true)
            conn.controlTransfer(0x21, 0x22, 0x03, ctrlIface.id, null, 0, 100)
        }

        try {
            return doRawReplUpload(conn, outEp, inEp, filename, content)
        } finally {
            conn.releaseInterface(dataIface)
            ctrlIface?.let { conn.releaseInterface(it) }
            conn.close()
        }
    }

    /**
     * Execute Python code on the Pico via raw REPL and return its stdout output.
     * Must be called while the reader is STOPPED.
     */
    fun executeCode(code: String, softReboot: Boolean = true): String {
        val device = findDevice() ?: return "ERROR: Pico not found"
        if (isBootselMode(device)) return "ERROR: Pico is in BOOTSEL mode"
        if (!usbManager.hasPermission(device)) return "ERROR: No USB permission"

        val dataIface = findCdcDataInterface(device) ?: return "ERROR: No CDC Data interface"
        val outEp = findBulkOutEndpoint(dataIface) ?: return "ERROR: No bulk OUT endpoint"
        val inEp = findBulkInEndpoint(dataIface) ?: return "ERROR: No bulk IN endpoint"

        val conn = usbManager.openDevice(device) ?: return "ERROR: Failed to open device"
        conn.claimInterface(dataIface, true)

        val ctrlIface = findCdcControlInterface(device)
        if (ctrlIface != null) {
            conn.claimInterface(ctrlIface, true)
            conn.controlTransfer(0x21, 0x22, 0x03, ctrlIface.id, null, 0, 100)
        }

        try {
            return doRawReplExec(conn, outEp, inEp, code, softReboot)
        } finally {
            conn.releaseInterface(dataIface)
            ctrlIface?.let { conn.releaseInterface(it) }
            conn.close()
        }
    }

    private fun sendBytes(conn: UsbDeviceConnection, ep: UsbEndpoint, data: ByteArray) {
        var offset = 0
        while (offset < data.size) {
            val chunk = minOf(data.size - offset, ep.maxPacketSize)
            val sent = conn.bulkTransfer(ep, data, offset, chunk, 1000)
            if (sent < 0) break
            offset += sent
        }
    }

    private fun readAll(conn: UsbDeviceConnection, ep: UsbEndpoint, timeoutMs: Int = 2000): String {
        val sb = StringBuilder()
        val buf = ByteArray(512)
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val n = conn.bulkTransfer(ep, buf, buf.size, 200)
            if (n > 0) {
                sb.append(String(buf, 0, n))
                // Reset deadline on data received
                // (but cap at original timeout to avoid infinite loops)
            }
        }
        return sb.toString()
    }

    private fun drainInput(conn: UsbDeviceConnection, ep: UsbEndpoint) {
        val buf = ByteArray(512)
        for (i in 0 until 20) {
            if (conn.bulkTransfer(ep, buf, buf.size, 50) <= 0) break
        }
    }

    private fun enterRawRepl(conn: UsbDeviceConnection, outEp: UsbEndpoint, inEp: UsbEndpoint): Boolean {
        // Ctrl+C twice to interrupt, then Ctrl+A for raw REPL
        sendBytes(conn, outEp, byteArrayOf(0x03, 0x03))
        Thread.sleep(200)
        drainInput(conn, inEp)
        sendBytes(conn, outEp, byteArrayOf(0x01))  // Ctrl+A
        Thread.sleep(200)
        val response = readAll(conn, inEp, 1000)
        Log.d(TAG, "Raw REPL entry response: ${response.take(200)}")
        return response.contains("raw REPL") || response.contains(">")
    }

    private fun exitRawRepl(conn: UsbDeviceConnection, outEp: UsbEndpoint, inEp: UsbEndpoint, softReboot: Boolean) {
        sendBytes(conn, outEp, byteArrayOf(0x02))  // Ctrl+B (exit raw REPL)
        Thread.sleep(100)
        if (softReboot) {
            sendBytes(conn, outEp, byteArrayOf(0x04))  // Ctrl+D (soft reboot)
            Thread.sleep(500)
        }
        drainInput(conn, inEp)
    }

    private fun rawReplExec(conn: UsbDeviceConnection, outEp: UsbEndpoint, inEp: UsbEndpoint,
                            code: String, readTimeoutMs: Int = 3000): String {
        // In raw REPL: send code, then Ctrl+D to execute
        sendBytes(conn, outEp, code.toByteArray())
        sendBytes(conn, outEp, byteArrayOf(0x04))  // Ctrl+D = execute
        // Raw REPL response: "OK" + stdout + "\x04" + stderr + "\x04"
        val response = readAll(conn, inEp, readTimeoutMs)
        Log.d(TAG, "Raw REPL exec response (${response.length} chars): ${response.take(500)}")
        return response
    }

    private fun doRawReplUpload(conn: UsbDeviceConnection, outEp: UsbEndpoint, inEp: UsbEndpoint,
                                 filename: String, content: ByteArray): String {
        if (!enterRawRepl(conn, outEp, inEp)) {
            return "Failed to enter raw REPL"
        }

        try {
            // Write file in chunks using base64 to avoid encoding issues
            val b64 = android.util.Base64.encodeToString(content, android.util.Base64.NO_WRAP)
            val chunkSize = 256  // base64 chars per chunk

            // Open file
            val openCode = "import ubinascii\nf=open('$filename','wb')\n"
            var response = rawReplExec(conn, outEp, inEp, openCode)
            if (response.contains("Traceback") || response.contains("Error")) {
                return "Failed to open file: $response"
            }

            // Write chunks
            var offset = 0
            while (offset < b64.length) {
                val end = minOf(offset + chunkSize, b64.length)
                val chunk = b64.substring(offset, end)
                val writeCode = "f.write(ubinascii.a2b_base64('$chunk'))\n"
                response = rawReplExec(conn, outEp, inEp, writeCode)
                if (response.contains("Traceback") || response.contains("Error")) {
                    return "Write failed at offset $offset: $response"
                }
                offset = end
            }

            // Close file
            response = rawReplExec(conn, outEp, inEp, "f.close()\nprint('OK:${content.size}')\n")
            Log.i(TAG, "Upload complete: $filename (${content.size} bytes)")
            return "OK: uploaded $filename (${content.size} bytes)"
        } finally {
            exitRawRepl(conn, outEp, inEp, softReboot = true)
        }
    }

    private fun doRawReplExec(conn: UsbDeviceConnection, outEp: UsbEndpoint, inEp: UsbEndpoint,
                               code: String, softReboot: Boolean): String {
        if (!enterRawRepl(conn, outEp, inEp)) {
            return "ERROR: Failed to enter raw REPL"
        }

        try {
            val response = rawReplExec(conn, outEp, inEp, code, 10000)
            // Parse raw REPL response: strip "OK" prefix and "\x04" delimiters
            val cleaned = response
                .replace("\u0004", "\n")
                .replace("OK", "")
                .trim()
            return cleaned
        } finally {
            exitRawRepl(conn, outEp, inEp, softReboot)
        }
    }

    private fun findCdcDataInterface(device: UsbDevice): UsbInterface? {
        // Only match CDC Data class (0x0A) — no fallback to vendor-specific.
        // Vendor-specific interfaces on BOOTSEL devices are PICOBOOT, not CDC.
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (iface.interfaceClass == 0x0A) {
                if (findBulkInEndpoint(iface) != null) return iface
            }
        }
        return null
    }

    private fun findCdcControlInterface(device: UsbDevice): UsbInterface? {
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (iface.interfaceClass == UsbConstants.USB_CLASS_COMM) {
                return iface
            }
        }
        return null
    }

    private fun findBulkInEndpoint(iface: UsbInterface): UsbEndpoint? {
        for (i in 0 until iface.endpointCount) {
            val ep = iface.getEndpoint(i)
            if (ep.direction == UsbConstants.USB_DIR_IN &&
                ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK
            ) {
                return ep
            }
        }
        return null
    }

    private fun findBulkOutEndpoint(iface: UsbInterface): UsbEndpoint? {
        for (i in 0 until iface.endpointCount) {
            val ep = iface.getEndpoint(i)
            if (ep.direction == UsbConstants.USB_DIR_OUT &&
                ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK
            ) {
                return ep
            }
        }
        return null
    }
}
