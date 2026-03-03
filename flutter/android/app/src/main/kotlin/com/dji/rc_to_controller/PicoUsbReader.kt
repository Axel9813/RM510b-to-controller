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
 * The Pico appears as a USB CDC ACM device with VID 0x2E8A.
 * PID varies by firmware config (0x0005 = CDC only, 0x0009 = CDC+MSC, etc.).
 * We match VID only, then claim the CDC **data** interface (class 0x0A)
 * and read from its bulk IN endpoint.
 */
class PicoUsbReader(
    private val usbManager: UsbManager,
    private val onBitmask: (Int) -> Unit,
    private val onError: (String) -> Unit
) {
    companion object {
        private const val TAG = "PicoUsbReader"
        private const val VID = 0x2E8A  // Raspberry Pi
        // Match VID only — PID varies: 0x0005 (CDC), 0x0009 (CDC+MSC), etc.
        private const val SYNC_BYTE = 0xAA
        private const val READ_TIMEOUT_MS = 100
    }

    @Volatile
    private var running = false
    private var thread: Thread? = null
    private var connection: UsbDeviceConnection? = null
    private var usbInterface: UsbInterface? = null

    val isRunning: Boolean get() = running

    fun findDevice(): UsbDevice? {
        // Log all USB devices for diagnostics
        for (device in usbManager.deviceList.values) {
            Log.d(TAG, "USB device on bus: VID=${device.vendorId.toString(16)} " +
                    "PID=${device.productId.toString(16)} name=${device.deviceName} " +
                    "ifaces=${device.interfaceCount}")
        }
        return usbManager.deviceList.values.firstOrNull { device ->
            device.vendorId == VID
        }
    }

    fun start(): Boolean {
        if (running) return true

        val device = findDevice()
        if (device == null) {
            onError("Pico not found (VID:${VID.toString(16)})")
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
        // CDC ACM devices typically have two interfaces:
        //   - CDC Control (class 0x02) — we skip this
        //   - CDC Data   (class 0x0A) — has bulk IN/OUT endpoints
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

        // CDC ACM: set line coding (115200 8N1) and enable DTR
        // Some MicroPython builds need DTR raised to start sending data.
        val ctrlIface = findCdcControlInterface(device)
        if (ctrlIface != null) {
            conn.claimInterface(ctrlIface, true)
            // SET_CONTROL_LINE_STATE: DTR=1, RTS=1
            conn.controlTransfer(
                0x21,  // bmRequestType: host-to-device, class, interface
                0x22,  // SET_CONTROL_LINE_STATE
                0x03,  // DTR | RTS
                ctrlIface.id,
                null, 0, 100
            )
        }

        // Send Ctrl+C (interrupt) + Ctrl+D (soft reboot) to ensure main.py starts.
        // If the Pico was left in REPL mode (e.g. after Thonny session), main.py
        // won't be running. This forces a restart regardless of current state.
        val outEndpoint = findBulkOutEndpoint(dataIface)
        if (outEndpoint != null) {
            val reset = byteArrayOf(0x03, 0x03, 0x04)  // Ctrl+C, Ctrl+C, Ctrl+D
            val sent = conn.bulkTransfer(outEndpoint, reset, reset.size, 500)
            Log.i(TAG, "Sent soft-reboot sequence ($sent bytes)")
            // Give MicroPython time to reboot and start main.py (~1.5s)
            Thread.sleep(1500)
        } else {
            Log.w(TAG, "No bulk OUT endpoint — cannot send soft-reboot")
        }

        connection = conn
        usbInterface = dataIface
        running = true

        val bufSize = maxOf(inEndpoint.maxPacketSize, 64)
        Log.i(TAG, "Endpoint maxPacketSize=${inEndpoint.maxPacketSize}, starting read thread")

        thread = Thread({
            Log.i(TAG, "Read thread started")
            val buffer = ByteArray(bufSize)
            // Ring buffer for frame parsing (handles partial reads)
            val ring = ByteArray(256)
            var ringLen = 0
            var readCount = 0
            var lastLogTime = System.currentTimeMillis()

            while (running) {
                val bytesRead = conn.bulkTransfer(inEndpoint, buffer, bufSize, READ_TIMEOUT_MS)
                readCount++

                // Periodic diagnostic log (every 3 seconds)
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

                if (bytesRead > 0) {
                    // Append to ring buffer
                    val space = ring.size - ringLen
                    val toCopy = minOf(bytesRead, space)
                    System.arraycopy(buffer, 0, ring, ringLen, toCopy)
                    ringLen += toCopy

                    // Parse all complete frames from ring
                    var i = 0
                    while (i + 2 < ringLen) {
                        if ((ring[i].toInt() and 0xFF) == SYNC_BYTE) {
                            val lo = ring[i + 1].toInt() and 0xFF
                            val hi = ring[i + 2].toInt() and 0xFF
                            val bitmask = lo or (hi shl 8)
                            onBitmask(bitmask)
                            i += 3
                        } else {
                            // Not a sync byte — skip to re-sync
                            i++
                        }
                    }

                    // Shift remaining bytes to front of ring
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
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            // CDC Data class = 0x0A
            if (iface.interfaceClass == 0x0A) {
                if (findBulkInEndpoint(iface) != null) return iface
            }
        }
        // Fallback: vendor-specific (0xFF) interface with bulk IN.
        // Explicitly skip COMM (0x02), HID (0x03), MSC (0x08) to avoid
        // claiming the wrong interface when Pico exposes mass storage.
        val skipClasses = setOf(
            UsbConstants.USB_CLASS_COMM,       // 0x02
            UsbConstants.USB_CLASS_HID,        // 0x03
            UsbConstants.USB_CLASS_MASS_STORAGE // 0x08
        )
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (iface.interfaceClass !in skipClasses) {
                if (findBulkInEndpoint(iface) != null) {
                    Log.w(TAG, "Using fallback interface $i class=0x${iface.interfaceClass.toString(16)}")
                    return iface
                }
            }
        }
        return null
    }

    private fun findCdcControlInterface(device: UsbDevice): UsbInterface? {
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            // CDC Control class = 0x02
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
