package com.dji.rc_to_controller

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.util.Log

/**
 * Reads 3-byte bitmask frames from a Raspberry Pi Pico running MicroPython
 * over USB CDC serial.
 *
 * Frame format: [0xAA] [bitmask_low] [bitmask_high]
 *
 * Handles two Pico states:
 *   PID 0x0003 — RP2 Boot (BOOTSEL mode): sends PICOBOOT reboot command
 *                to force the Pico into application (MicroPython) mode.
 *   PID 0x0005+ — MicroPython CDC: claims the CDC Data interface (class 0x0A)
 *                 and reads bitmask frames from its bulk IN endpoint.
 */
class PicoUsbReader(
    private val usbManager: UsbManager,
    private val onBitmask: (Int) -> Unit,
    private val onError: (String) -> Unit
) {
    companion object {
        private const val TAG = "PicoUsbReader"
        private const val VID = 0x2E8A          // Raspberry Pi
        private const val PID_BOOTSEL = 0x0003  // RP2 Boot (BOOTSEL mode)
        private const val SYNC_BYTE = 0xAA
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
                    while (i + 2 < ringLen) {
                        if ((ring[i].toInt() and 0xFF) == SYNC_BYTE) {
                            val lo = ring[i + 1].toInt() and 0xFF
                            val hi = ring[i + 2].toInt() and 0xFF
                            val bitmask = lo or (hi shl 8)
                            onBitmask(bitmask)
                            i += 3
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
