package com.dji.rc_to_controller

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {

    companion object {
        private const val RC_METHOD_CHANNEL = "com.dji.rc/control"
        private const val RC_EVENT_CHANNEL  = "com.dji.rc/state"
        private const val PICO_METHOD_CHANNEL = "com.dji.rc/pico"
        private const val PICO_EVENT_CHANNEL  = "com.dji.rc/pico_state"
    }

    private var rcPlugin: RcPlugin? = null
    private var picoPlugin: PicoPlugin? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val messenger = flutterEngine.dartExecutor.binaryMessenger

        // DJI RC joystick (HID)
        val rc = RcPlugin(this)
        rcPlugin = rc
        MethodChannel(messenger, RC_METHOD_CHANNEL).setMethodCallHandler(rc)
        EventChannel(messenger, RC_EVENT_CHANNEL).setStreamHandler(rc)

        // Raspberry Pi Pico (CDC serial)
        val pico = PicoPlugin(this)
        picoPlugin = pico
        MethodChannel(messenger, PICO_METHOD_CHANNEL).setMethodCallHandler(pico)
        EventChannel(messenger, PICO_EVENT_CHANNEL).setStreamHandler(pico)

        // WiFi MulticastLock
        MethodChannel(messenger, WifiMulticastLockPlugin.CHANNEL)
            .setMethodCallHandler(WifiMulticastLockPlugin(this))
    }

    override fun onDestroy() {
        rcPlugin?.dispose()
        rcPlugin = null
        picoPlugin?.dispose()
        picoPlugin = null
        super.onDestroy()
    }
}
