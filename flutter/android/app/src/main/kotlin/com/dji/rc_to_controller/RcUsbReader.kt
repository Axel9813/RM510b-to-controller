package com.dji.rc_to_controller

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.util.Log

class RcUsbReader(
    private val usbManager: UsbManager,
    private val onState: (RcState) -> Unit,
    private val onError: (String) -> Unit
) {
    companion object {
        private const val TAG = "RcUsbReader"
        private const val VID = 0x2CA3  // DJI
        private const val PID = 0x1501  // Embedded joystick
        private const val PACKET_SIZE = 18
        private const val READ_TIMEOUT_MS = 100
    }

    @Volatile
    private var running = false
    private var thread: Thread? = null
    private var connection: UsbDeviceConnection? = null
    private var usbInterface: UsbInterface? = null

    val isRunning: Boolean get() = running

    fun findDevice(): UsbDevice? {
        return usbManager.deviceList.values.firstOrNull { device ->
            device.vendorId == VID && device.productId == PID
        }
    }

    fun start(): Boolean {
        if (running) return true

        val device = findDevice()
        if (device == null) {
            onError("DJI RC joystick not found (VID:${VID.toString(16)} PID:${PID.toString(16)})")
            return false
        }

        if (!usbManager.hasPermission(device)) {
            onError("No USB permission for device")
            return false
        }

        val iface = findHidInterface(device)
        if (iface == null) {
            onError("No HID interface found on device")
            return false
        }

        val endpoint = findInEndpoint(iface)
        if (endpoint == null) {
            onError("No IN endpoint found on HID interface")
            return false
        }

        val conn = usbManager.openDevice(device)
        if (conn == null) {
            onError("Failed to open USB device")
            return false
        }

        if (!conn.claimInterface(iface, true)) {
            conn.close()
            onError("Failed to claim interface (force=true)")
            return false
        }

        connection = conn
        usbInterface = iface
        running = true

        // Android's UsbDeviceConnection only exposes bulkTransfer() — there is no
        // interruptTransfer() in the public SDK. For HID interrupt endpoints,
        // bulkTransfer() works BUT the buffer length MUST equal the endpoint's
        // maxPacketSize, not the expected payload size. The DJI RC sends 18-byte
        // HID reports; if the endpoint's maxPacketSize is larger (typically 64),
        // passing length=18 returns -1. We allocate a buffer of maxPacketSize and
        // let fromHidPacket() validate the header bytes.
        val bufSize = maxOf(endpoint.maxPacketSize, PACKET_SIZE)
        Log.i(TAG, "Endpoint maxPacketSize=$bufSize, type=${endpoint.type}")

        thread = Thread({
            Log.i(TAG, "Read thread started")
            val buffer = ByteArray(bufSize)
            while (running) {
                val bytesRead = conn.bulkTransfer(endpoint, buffer, bufSize, READ_TIMEOUT_MS)
                if (bytesRead >= PACKET_SIZE) {
                    val state = RcState.fromHidPacket(buffer)
                    if (state != null) {
                        onState(state)
                    }
                } else if (bytesRead < 0 && running) {
                    // Negative = timeout or error; timeout is normal, just retry
                }
            }
            Log.i(TAG, "Read thread stopped")
        }, "RcUsbReader")
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

    private fun findHidInterface(device: UsbDevice): UsbInterface? {
        // First pass: prefer HID class (3) interfaces that have an IN interrupt endpoint
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (iface.interfaceClass == UsbConstants.USB_CLASS_HID) {
                if (findInEndpoint(iface) != null) return iface
            }
        }
        // Second pass: vendor-specific (255) with an IN interrupt endpoint
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (iface.interfaceClass == UsbConstants.USB_CLASS_VENDOR_SPEC) {
                if (findInEndpoint(iface) != null) return iface
            }
        }
        // Fallback: any interface with any IN endpoint
        for (i in 0 until device.interfaceCount) {
            val iface = device.getInterface(i)
            if (findInEndpoint(iface) != null) return iface
        }
        return null
    }

    /**
     * Find an IN endpoint, preferring interrupt type (HID) over bulk.
     */
    private fun findInEndpoint(iface: UsbInterface): UsbEndpoint? {
        var fallback: UsbEndpoint? = null
        for (i in 0 until iface.endpointCount) {
            val ep = iface.getEndpoint(i)
            if (ep.direction == UsbConstants.USB_DIR_IN) {
                if (ep.type == UsbConstants.USB_ENDPOINT_XFER_INT) return ep  // preferred
                if (fallback == null) fallback = ep
            }
        }
        return fallback
    }
}
