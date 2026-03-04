package com.dji.rc_to_controller

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import kotlin.math.abs

/**
 * Reads Game Rotation Vector (or full Rotation Vector) sensor data and
 * streams relative pitch/yaw/roll (radians) to Flutter via EventChannel.
 *
 * The orientation is always relative to a reference point set on start
 * or via the "zero" command, so the user can hold the controller at any
 * angle and re-zero.
 */
class SensorPlugin(private val context: Context) :
    MethodChannel.MethodCallHandler,
    EventChannel.StreamHandler,
    SensorEventListener {

    companion object {
        private const val TAG = "SensorPlugin"
        private const val EMIT_INTERVAL_MS = 20L  // 50 Hz to match WebSocket rate
        private const val CHANGE_THRESHOLD = 0.001 // ~0.06 degrees — avoid flooding identical data
    }

    private val sensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val mainHandler = Handler(Looper.getMainLooper())

    private var eventSink: EventChannel.EventSink? = null
    private var running = false
    private var useGameRotation = true  // true = game (no mag), false = full (with mag)

    // Reference rotation matrix (3×3 row-major flat array, set on "zero")
    @Volatile private var refMatrix: FloatArray? = null

    // Working arrays (avoid allocations in onSensorChanged)
    private val rotationVector = FloatArray(4)
    private val currentMatrix = FloatArray(9)
    private val relativeMatrix = FloatArray(9)
    private val orientation = FloatArray(3)

    // Last emitted values + timestamp for throttling
    private var lastPitch = 0.0
    private var lastYaw = 0.0
    private var lastRoll = 0.0
    private var lastEmitTime = 0L

    // ── MethodChannel ────────────────────────────────────────────────────

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "start" -> {
                val ok = handleStart()
                result.success(ok)
            }
            "stop" -> {
                handleStop()
                result.success(true)
            }
            "zero" -> {
                refMatrix = null  // next sensor event sets new reference
                Log.i(TAG, "Zero requested — will re-reference on next reading")
                result.success(true)
            }
            "setSensorType" -> {
                val type = call.argument<String>("type") ?: "game"
                val wasRunning = running
                if (wasRunning) handleStop()
                useGameRotation = (type == "game")
                if (wasRunning) handleStart()
                Log.i(TAG, "Sensor type set to: ${if (useGameRotation) "game" else "full"}")
                result.success(true)
            }
            "status" -> {
                val sensorType = if (useGameRotation)
                    Sensor.TYPE_GAME_ROTATION_VECTOR
                else
                    Sensor.TYPE_ROTATION_VECTOR
                result.success(mapOf(
                    "running" to running,
                    "mode" to if (useGameRotation) "game" else "full",
                    "sensorAvailable" to (sensorManager.getDefaultSensor(sensorType) != null),
                    "hasReference" to (refMatrix != null),
                ))
            }
            else -> result.notImplemented()
        }
    }

    // ── Lifecycle ────────────────────────────────────────────────────────

    private fun handleStart(): Boolean {
        if (running) return true

        val sensorType = if (useGameRotation)
            Sensor.TYPE_GAME_ROTATION_VECTOR
        else
            Sensor.TYPE_ROTATION_VECTOR

        val sensor = sensorManager.getDefaultSensor(sensorType)
        if (sensor == null) {
            val name = if (useGameRotation) "GAME_ROTATION_VECTOR" else "ROTATION_VECTOR"
            Log.w(TAG, "Sensor $name not available on this device")
            return false
        }

        refMatrix = null  // auto-zero on start
        lastEmitTime = 0L
        sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_GAME)
        running = true
        Log.i(TAG, "Started with ${if (useGameRotation) "game" else "full"} rotation vector " +
                "(${sensor.name}, max ${sensor.maximumRange})")
        return true
    }

    private fun handleStop() {
        if (!running) return
        sensorManager.unregisterListener(this)
        running = false
        refMatrix = null
        Log.i(TAG, "Stopped")
    }

    // ── SensorEventListener ─────────────────────────────────────────────

    override fun onSensorChanged(event: SensorEvent) {
        // Throttle to EMIT_INTERVAL_MS
        val now = System.currentTimeMillis()
        if (now - lastEmitTime < EMIT_INTERVAL_MS) return
        lastEmitTime = now

        // Extract rotation vector values (x, y, z, and optionally w)
        val valCount = event.values.size.coerceAtMost(4)
        System.arraycopy(event.values, 0, rotationVector, 0, valCount)
        if (valCount < 4) {
            // Compute w from x,y,z for 3-element rotation vectors
            val x = rotationVector[0]; val y = rotationVector[1]; val z = rotationVector[2]
            val dot = x * x + y * y + z * z
            rotationVector[3] = if (dot < 1.0f) Math.sqrt((1.0 - dot).toDouble()).toFloat() else 0f
        }

        // Convert quaternion to 3×3 rotation matrix
        SensorManager.getRotationMatrixFromVector(currentMatrix, rotationVector)

        // Snapshot refMatrix to local — avoids TOCTOU race with zero() on main thread
        val ref = refMatrix
        if (ref == null) {
            refMatrix = currentMatrix.copyOf()
            Log.i(TAG, "Reference orientation set")
            return
        }

        // Compute relative rotation: R_ref^T × R_current
        // Row 0 of result = row 0 of ref^T dotted with columns of current
        relativeMatrix[0] = ref[0] * currentMatrix[0] + ref[3] * currentMatrix[3] + ref[6] * currentMatrix[6]
        relativeMatrix[1] = ref[0] * currentMatrix[1] + ref[3] * currentMatrix[4] + ref[6] * currentMatrix[7]
        relativeMatrix[2] = ref[0] * currentMatrix[2] + ref[3] * currentMatrix[5] + ref[6] * currentMatrix[8]
        // Row 1
        relativeMatrix[3] = ref[1] * currentMatrix[0] + ref[4] * currentMatrix[3] + ref[7] * currentMatrix[6]
        relativeMatrix[4] = ref[1] * currentMatrix[1] + ref[4] * currentMatrix[4] + ref[7] * currentMatrix[7]
        relativeMatrix[5] = ref[1] * currentMatrix[2] + ref[4] * currentMatrix[5] + ref[7] * currentMatrix[8]
        // Row 2
        relativeMatrix[6] = ref[2] * currentMatrix[0] + ref[5] * currentMatrix[3] + ref[8] * currentMatrix[6]
        relativeMatrix[7] = ref[2] * currentMatrix[1] + ref[5] * currentMatrix[4] + ref[8] * currentMatrix[7]
        relativeMatrix[8] = ref[2] * currentMatrix[2] + ref[5] * currentMatrix[5] + ref[8] * currentMatrix[8]

        // Extract Euler angles from relative rotation matrix
        // orientation[0] = azimuth (yaw), [1] = pitch, [2] = roll — all in radians
        SensorManager.getOrientation(relativeMatrix, orientation)

        val yaw   = orientation[0].toDouble()   // azimuth, ±π
        val pitch = orientation[1].toDouble()   // ±π/2
        val roll  = orientation[2].toDouble()   // ±π

        // Guard against degenerate sensor data
        if (pitch.isNaN() || yaw.isNaN() || roll.isNaN()) return

        // Only emit if changed beyond threshold
        if (abs(pitch - lastPitch) < CHANGE_THRESHOLD &&
            abs(yaw - lastYaw) < CHANGE_THRESHOLD &&
            abs(roll - lastRoll) < CHANGE_THRESHOLD) {
            return
        }

        lastPitch = pitch
        lastYaw = yaw
        lastRoll = roll

        // Send as list [pitch, yaw, roll] in radians
        mainHandler.post {
            eventSink?.success(listOf(pitch, yaw, roll))
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Not needed for rotation vector
    }

    // ── EventChannel ────────────────────────────────────────────────────

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
    }

    // ── Cleanup ─────────────────────────────────────────────────────────

    fun dispose() {
        handleStop()
    }
}
