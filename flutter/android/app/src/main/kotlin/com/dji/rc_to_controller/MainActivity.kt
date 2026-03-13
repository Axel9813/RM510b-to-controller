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
        private const val PICO_MONITOR_EVENT_CHANNEL = "com.dji.rc/pico_monitor"
        private const val SENSOR_METHOD_CHANNEL = "com.dji.rc/sensor"
        private const val SENSOR_EVENT_CHANNEL  = "com.dji.rc/sensor_state"
    }

    private var rcPlugin: RcPlugin? = null
    private var picoPlugin: PicoPlugin? = null
    private var sensorPlugin: SensorPlugin? = null
    private var btPlugin: BluetoothPlugin? = null
    private var hapticPlugin: HapticPlugin? = null

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
        EventChannel(messenger, PICO_MONITOR_EVENT_CHANNEL).setStreamHandler(pico.monitorStreamHandler)

        // IMU Sensor (gyro/accelerometer)
        val sensor = SensorPlugin(this)
        sensorPlugin = sensor
        MethodChannel(messenger, SENSOR_METHOD_CHANNEL).setMethodCallHandler(sensor)
        EventChannel(messenger, SENSOR_EVENT_CHANNEL).setStreamHandler(sensor)

        // WiFi MulticastLock
        MethodChannel(messenger, WifiMulticastLockPlugin.CHANNEL)
            .setMethodCallHandler(WifiMulticastLockPlugin(this))

        // Bluetooth RFCOMM
        val bt = BluetoothPlugin(this)
        btPlugin = bt
        MethodChannel(messenger, BluetoothPlugin.METHOD_CHANNEL).setMethodCallHandler(bt)
        EventChannel(messenger, BluetoothPlugin.EVENT_CHANNEL).setStreamHandler(bt)

        // Haptic feedback (vibration for gamepad rumble)
        val haptic = HapticPlugin(this)
        hapticPlugin = haptic
        MethodChannel(messenger, HapticPlugin.METHOD_CHANNEL).setMethodCallHandler(haptic)

    }

    override fun onDestroy() {
        rcPlugin?.dispose()
        rcPlugin = null
        picoPlugin?.dispose()
        picoPlugin = null
        sensorPlugin?.dispose()
        sensorPlugin = null
        btPlugin?.dispose()
        btPlugin = null
        super.onDestroy()
    }
}
