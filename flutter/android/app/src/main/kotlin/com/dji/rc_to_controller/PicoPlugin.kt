package com.dji.rc_to_controller

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

class PicoPlugin(private val context: Context) :
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {

    companion object {
        private const val TAG = "PicoPlugin"
        private const val ACTION_USB_PERMISSION = "com.dji.rc_to_controller.PICO_USB_PERMISSION"
        private const val BOOTSEL_REBOOT_WAIT_MS = 4000L  // wait for Pico to reboot + re-enumerate
        private const val BOOTSEL_MAX_RETRIES = 5
    }

    private val usbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager
    private val mainHandler = Handler(Looper.getMainLooper())
    private val startLock = Object()

    @Volatile private var reader: PicoUsbReader? = null
    private var eventSink: EventChannel.EventSink? = null
    private var lastError: String? = null
    private var lastBitmask: Int = -1

    private val usbPermissionReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            if (intent.action == ACTION_USB_PERMISSION) {
                val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                if (granted) {
                    Log.i(TAG, "USB permission granted — starting Pico reader")
                    // After permission, the device might be BOOTSEL — handle on background thread
                    Thread { handleStartWithBootselRecovery() }.start()
                } else {
                    lastError = "USB permission denied by user"
                    Log.w(TAG, lastError!!)
                }
            }
        }
    }

    init {
        val filter = IntentFilter(ACTION_USB_PERMISSION)
        context.registerReceiver(usbPermissionReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
    }

    // --- MethodChannel.MethodCallHandler ---

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "start" -> {
                // Run on background thread since BOOTSEL recovery involves sleeps
                Thread {
                    val started = handleStartWithBootselRecovery()
                    mainHandler.post { result.success(started) }
                }.start()
            }
            "stop" -> {
                handleStop()
                result.success(true)
            }
            "status" -> {
                result.success(getStatus())
            }
            else -> result.notImplemented()
        }
    }

    /**
     * Main start logic with BOOTSEL recovery.
     *
     * If the Pico is in BOOTSEL mode (PID 0x0003), sends a PICOBOOT reboot
     * command and waits for it to re-enumerate as MicroPython CDC.
     * Retries up to BOOTSEL_MAX_RETRIES times.
     */
    private fun handleStartWithBootselRecovery(): Boolean {
        synchronized(startLock) {
        if (reader?.isRunning == true) return true

        // Stop any previous reader that isn't running (stale from permission flow)
        reader?.stop()
        reader = null

        for (attempt in 1..BOOTSEL_MAX_RETRIES) {
            val tempReader = PicoUsbReader(usbManager, ::onBitmask, ::onReaderError)
            val device = tempReader.findDevice()

            if (device == null) {
                lastError = "Pico not found"
                Log.w(TAG, "Pico USB device not found on bus")
                return false
            }

            Log.i(TAG, "Pico found: VID=${device.vendorId.toString(16)} " +
                    "PID=${device.productId.toString(16)} (attempt $attempt)")

            // Check if Pico is in BOOTSEL mode
            if (tempReader.isBootselMode(device)) {
                Log.w(TAG, "Pico is in BOOTSEL mode — sending reboot command")
                lastError = "Pico in BOOTSEL mode — rebooting... (attempt $attempt)"

                // Request permission if needed
                if (!usbManager.hasPermission(device)) {
                    Log.i(TAG, "Requesting USB permission for BOOTSEL device")
                    reader = tempReader
                    mainHandler.post { requestPermission(device) }
                    return false  // will resume after permission grant
                }

                // Send PICOBOOT reboot command
                val rebooted = tempReader.rebootFromBootsel(device)
                if (rebooted) {
                    Log.i(TAG, "PICOBOOT reboot sent — waiting ${BOOTSEL_REBOOT_WAIT_MS}ms for MicroPython")
                    Thread.sleep(BOOTSEL_REBOOT_WAIT_MS)
                    // Loop back to find the device again (should now be MicroPython CDC)
                    continue
                } else {
                    Log.e(TAG, "PICOBOOT reboot command failed")
                    lastError = "Failed to reboot Pico from BOOTSEL mode"
                    return false
                }
            }

            // Not BOOTSEL — try normal CDC start
            if (!usbManager.hasPermission(device)) {
                Log.i(TAG, "No USB permission — requesting...")
                reader = tempReader
                mainHandler.post { requestPermission(device) }
                return false  // will start after permission grant
            }

            Log.i(TAG, "USB permission OK — starting CDC reader")
            reader = tempReader
            return startReader()
        }

        lastError = "Pico stuck in BOOTSEL mode after $BOOTSEL_MAX_RETRIES reboot attempts"
        Log.e(TAG, lastError!!)
        return false
        } // synchronized
    }

    private fun startReader(): Boolean {
        val r = reader ?: return false
        val ok = r.start()
        if (!ok) {
            lastError = lastError ?: "Failed to start Pico reader"
        } else {
            lastError = null
            lastBitmask = -1
        }
        return ok
    }

    private fun handleStop() {
        reader?.stop()
        reader = null
        lastBitmask = -1
    }

    private fun requestPermission(device: UsbDevice) {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        val pi = PendingIntent.getBroadcast(context, 1, Intent(ACTION_USB_PERMISSION), flags)
        usbManager.requestPermission(device, pi)
    }

    private fun onBitmask(bitmask: Int) {
        if (bitmask == lastBitmask) return
        lastBitmask = bitmask
        mainHandler.post {
            eventSink?.success(bitmask)
        }
    }

    private fun onReaderError(error: String) {
        lastError = error
        Log.e(TAG, error)
    }

    private fun getStatus(): Map<String, Any?> {
        val r = reader
        val probe = r ?: PicoUsbReader(usbManager, {}, {})
        val device = probe.findDevice()
        val info = mutableMapOf<String, Any?>(
            "connected" to (r?.isRunning == true),
            "deviceFound" to (device != null),
            "error" to lastError,
            "lastBitmask" to lastBitmask
        )
        if (device != null) {
            info["vid"] = "0x${device.vendorId.toString(16)}"
            info["pid"] = "0x${device.productId.toString(16)}"
            info["product"] = (device.productName ?: "unknown")
            info["interfaces"] = device.interfaceCount
            info["bootsel"] = probe.isBootselMode(device)
        }
        return info
    }

    // --- EventChannel.StreamHandler ---

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
    }

    fun dispose() {
        handleStop()
        try {
            context.unregisterReceiver(usbPermissionReceiver)
        } catch (_: Exception) {}
    }
}
