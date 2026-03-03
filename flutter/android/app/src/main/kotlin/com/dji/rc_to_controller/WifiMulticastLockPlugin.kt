package com.dji.rc_to_controller

import android.content.Context
import android.net.wifi.WifiManager
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Exposes WifiManager.MulticastLock to Flutter via MethodChannel "com.dji.rc/multicast".
 *
 * Without a MulticastLock acquired, Android's WiFi driver silently discards
 * incoming UDP broadcast/multicast packets — so the discovery responses from
 * the PC never reach the Flutter socket even though CHANGE_WIFI_MULTICAST_STATE
 * is declared in the manifest.
 *
 * Flutter side calls:
 *   acquire()   — before opening the UDP socket
 *   release()   — after closing it
 */
class WifiMulticastLockPlugin(private val context: Context) : MethodChannel.MethodCallHandler {

    companion object {
        const val CHANNEL = "com.dji.rc/multicast"
        private const val LOCK_TAG = "dji_rc_discovery"
    }

    private var lock: WifiManager.MulticastLock? = null

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "acquire" -> {
                try {
                    if (lock == null) {
                        val wm = context.applicationContext
                            .getSystemService(Context.WIFI_SERVICE) as WifiManager
                        lock = wm.createMulticastLock(LOCK_TAG).also {
                            it.setReferenceCounted(false)
                        }
                    }
                    lock?.acquire()
                    result.success(null)
                } catch (e: Exception) {
                    // Non-fatal — proceed without the lock (will work on some devices/ROMs)
                    result.success(null)
                }
            }
            "release" -> {
                try {
                    lock?.release()
                } catch (_: Exception) {}
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }
}
