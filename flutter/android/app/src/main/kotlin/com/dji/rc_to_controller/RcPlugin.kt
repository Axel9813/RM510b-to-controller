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
    }

    private val usbManager = context.getSystemService(Context.USB_SERVICE) as UsbManager
    private val mainHandler = Handler(Looper.getMainLooper())

    private var reader: RcUsbReader? = null
    private var eventSink: EventChannel.EventSink? = null
    private var lastError: String? = null

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

    init {
        val filter = IntentFilter(ACTION_USB_PERMISSION)
        context.registerReceiver(usbPermissionReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
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
            "status" -> {
                result.success(getStatus())
            }
            else -> result.notImplemented()
        }
    }

    private fun handleStart(): Boolean {
        if (reader?.isRunning == true) return true

        val tempReader = RcUsbReader(usbManager, ::onRcState, ::onReaderError)
        val device = tempReader.findDevice()

        if (device == null) {
            lastError = "DJI RC joystick not found"
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

    private fun startReader(): Boolean {
        val r = reader ?: return false
        val ok = r.start()
        if (!ok) {
            lastError = "Failed to start USB reader"
        } else {
            lastError = null
        }
        return ok
    }

    private fun handleStop() {
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
        try {
            context.unregisterReceiver(usbPermissionReceiver)
        } catch (_: Exception) {}
    }
}
