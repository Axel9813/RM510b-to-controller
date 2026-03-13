package com.dji.rc_to_controller

import android.content.Context
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.Handler
import android.os.Looper
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Triggers device vibration to relay gamepad rumble feedback from the PC.
 *
 * Uses a long one-shot vibration (sustained) and refreshes it periodically
 * to maintain continuous vibration without pulsing artifacts.
 */
class HapticPlugin(context: Context) : MethodChannel.MethodCallHandler {

    companion object {
        private const val TAG = "HapticPlugin"
        const val METHOD_CHANNEL = "com.dji.rc/haptic"
        private const val VIBRATION_DURATION_MS = 5000L  // long one-shot
        private const val REFRESH_INTERVAL_MS = 4000L    // refresh before it expires
    }

    private val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    private val handler = Handler(Looper.getMainLooper())
    private var currentAmplitude = 0
    private var active = false

    private val refreshRunnable = object : Runnable {
        override fun run() {
            if (active && currentAmplitude > 0) {
                vibrator?.vibrate(
                    VibrationEffect.createOneShot(VIBRATION_DURATION_MS, currentAmplitude)
                )
                handler.postDelayed(this, REFRESH_INTERVAL_MS)
            }
        }
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "rumble" -> {
                val large = call.argument<Int>("large") ?: 0
                val small = call.argument<Int>("small") ?: 0
                doRumble(large, small)
                result.success(null)
            }
            "cancel" -> {
                stopVibration()
                result.success(null)
            }
            "hasVibrator" -> {
                result.success(vibrator?.hasVibrator() == true)
            }
            else -> result.notImplemented()
        }
    }

    private fun doRumble(largeMotor: Int, smallMotor: Int) {
        if (vibrator == null || !vibrator.hasVibrator()) return

        if (largeMotor == 0 && smallMotor == 0) {
            stopVibration()
            return
        }

        val amplitude = maxOf(largeMotor, smallMotor).coerceIn(1, 255)

        if (amplitude == currentAmplitude && active) return
        currentAmplitude = amplitude

        // Start (or restart) a long one-shot vibration
        vibrator.vibrate(VibrationEffect.createOneShot(VIBRATION_DURATION_MS, amplitude))

        if (!active) {
            active = true
            handler.postDelayed(refreshRunnable, REFRESH_INTERVAL_MS)
        }
    }

    private fun stopVibration() {
        if (active) {
            active = false
            currentAmplitude = 0
            handler.removeCallbacks(refreshRunnable)
            vibrator?.cancel()
        }
    }
}
