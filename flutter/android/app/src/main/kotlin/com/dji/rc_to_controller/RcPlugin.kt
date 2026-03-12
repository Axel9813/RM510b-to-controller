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

class RcPlugin(private val context: Context) : MethodChannel.MethodCallHandler, EventChannel.StreamHandler {

    companion object {
        private const val TAG = "RcPlugin"
        private const val ACTION_USB_PERMISSION = "com.dji.rc_to_controller.USB_PERMISSION"
        private const val MAX_RETRY = 5
        private const val RETRY_DELAY_MS = 3000L
    }

    private val usbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager
    private val mainHandler = Handler(Looper.getMainLooper())

    private var reader: RcUsbReader? = null
    private var eventSink: EventChannel.EventSink? = null
    private var lastError: String? = null
    @Volatile private var retryPending = false
    @Volatile private var startRequested = false

    private val usbPermissionReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            if (intent.action == ACTION_USB_PERMISSION) {
                val granted = intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                if (granted) {
                    Log.i(TAG, "USB permission granted, starting reader")
                    startReader()
                } else {
                    lastError = "USB permission denied by user"
                    Log.w(TAG, lastError!!)
                }
            }
        }
    }

    private val usbAttachReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            if (intent.action == UsbManager.ACTION_USB_DEVICE_ATTACHED) {
                val device = intent.getParcelableExtra<UsbDevice>(UsbManager.EXTRA_DEVICE)
                Log.i(TAG, "USB device attached: VID=${device?.vendorId?.toString(16)} PID=${device?.productId?.toString(16)}")
                // If we previously requested start but device wasn't found, try again
                if (startRequested && reader?.isRunning != true) {
                    Log.i(TAG, "Auto-retrying RC start after USB attach")
                    handleStart()
                }
            }
        }
    }

    init {
        val permFilter = IntentFilter(ACTION_USB_PERMISSION)
        context.registerReceiver(usbPermissionReceiver, permFilter, Context.RECEIVER_NOT_EXPORTED)
        val attachFilter = IntentFilter(UsbManager.ACTION_USB_DEVICE_ATTACHED)
        context.registerReceiver(usbAttachReceiver, attachFilter, Context.RECEIVER_NOT_EXPORTED)
    }

    // --- MethodChannel.MethodCallHandler ---

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "start" -> {
                val started = handleStart()
                result.success(started)
            }
            "stop" -> {
                handleStop()
                result.success(true)
            }
            "reconnect" -> {
                handleStop()
                retryCount = 0
                val started = handleStart()
                result.success(started)
            }
            "status" -> {
                result.success(getStatus())
            }
            else -> result.notImplemented()
        }
    }

    private fun handleStart(): Boolean {
        startRequested = true
        if (reader?.isRunning == true) return true

        val tempReader = RcUsbReader(usbManager, ::onRcState, ::onReaderError)
        val device = tempReader.findDevice()

        if (device == null) {
            lastError = "DJI RC joystick not found"
            scheduleRetry()
            return false
        }

        if (!usbManager.hasPermission(device)) {
            // Request permission; reader will start from the broadcast receiver
            reader = tempReader
            requestPermission(device)
            return false // not started yet, will start after permission grant
        }

        reader = tempReader
        return startReader()
    }

    private var retryCount = 0

    private fun scheduleRetry() {
        if (retryPending || reader?.isRunning == true) return
        if (retryCount >= MAX_RETRY) {
            Log.w(TAG, "RC start: max retries ($MAX_RETRY) reached, giving up. Use reconnect to try again.")
            return
        }
        retryPending = true
        retryCount++
        Log.i(TAG, "RC start: scheduling retry $retryCount/$MAX_RETRY in ${RETRY_DELAY_MS}ms")
        mainHandler.postDelayed({
            retryPending = false
            if (reader?.isRunning != true && startRequested) {
                handleStart()
            }
        }, RETRY_DELAY_MS)
    }

    private fun startReader(): Boolean {
        val r = reader ?: return false
        val ok = r.start()
        if (!ok) {
            lastError = "Failed to start USB reader"
            scheduleRetry()
        } else {
            lastError = null
            retryCount = 0
        }
        return ok
    }

    private fun handleStop() {
        startRequested = false
        retryCount = 0
        mainHandler.removeCallbacksAndMessages(null)
        retryPending = false
        reader?.stop()
        reader = null
    }

    private fun requestPermission(device: UsbDevice) {
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        val pi = PendingIntent.getBroadcast(context, 0, Intent(ACTION_USB_PERMISSION), flags)
        usbManager.requestPermission(device, pi)
    }

    private fun onRcState(state: RcState) {
        mainHandler.post {
            eventSink?.success(state.toMap())
        }
    }

    private fun onReaderError(error: String) {
        lastError = error
        Log.e(TAG, error)
    }

    private fun getStatus(): Map<String, Any?> {
        val r = reader
        return mapOf(
            "connected" to (r?.isRunning == true),
            "deviceFound" to (r?.findDevice() != null || RcUsbReader(usbManager, {}, {}).findDevice() != null),
            "error" to lastError
        )
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
        try { context.unregisterReceiver(usbPermissionReceiver) } catch (_: Exception) {}
        try { context.unregisterReceiver(usbAttachReceiver) } catch (_: Exception) {}
    }
}
