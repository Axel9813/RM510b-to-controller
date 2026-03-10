package com.dji.rc_to_controller

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothSocket
import android.content.Context
import android.util.Log
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicReference

/**
 * Platform channel plugin for raw RFCOMM Bluetooth connections.
 *
 * Two send paths on the write thread:
 * - "send" (state): latest-value only, older writes dropped (AtomicReference)
 * - "sendControl" (ping/hello/events): queued, guaranteed delivery (ConcurrentLinkedQueue)
 */
class BluetoothPlugin(private val context: Context) :
    MethodChannel.MethodCallHandler, EventChannel.StreamHandler {

    companion object {
        const val METHOD_CHANNEL = "com.dji.rc/bluetooth"
        const val EVENT_CHANNEL = "com.dji.rc/bluetooth_data"
        private const val TAG = "BluetoothPlugin"
        private val SPP_UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    }

    private val adapter: BluetoothAdapter? = BluetoothAdapter.getDefaultAdapter()
    private var socket: BluetoothSocket? = null
    private var inputStream: InputStream? = null
    private var outputStream: OutputStream? = null
    private var readThread: Thread? = null
    private var writeThread: Thread? = null
    private var eventSink: EventChannel.EventSink? = null
    @Volatile private var connected = false
    @Volatile private var connectionGeneration = 0  // guards stale endOfStream

    // State data: only latest value kept (droppable)
    private val pendingState = AtomicReference<ByteArray?>(null)
    // Control messages: queued, guaranteed delivery
    private val controlQueue = ConcurrentLinkedQueue<ByteArray>()

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "isAvailable" -> result.success(adapter != null && adapter.isEnabled)
            "getPairedDevices" -> getPairedDevices(result)
            "connect" -> {
                val address = call.argument<String>("address")
                val channel = call.argument<Int>("channel")
                if (address == null) {
                    result.error("INVALID", "address is required", null)
                    return
                }
                Thread { connect(address, channel, result) }.start()
            }
            "disconnect" -> {
                disconnect()
                result.success(true)
            }
            "send" -> {
                val data = call.argument<ByteArray>("data")
                if (data != null) {
                    pendingState.set(data)
                    result.success(true)
                } else {
                    result.error("INVALID", "data is required", null)
                }
            }
            "sendControl" -> {
                val data = call.argument<ByteArray>("data")
                if (data != null) {
                    controlQueue.add(data)
                    result.success(true)
                } else {
                    result.error("INVALID", "data is required", null)
                }
            }
            "isConnected" -> result.success(connected)
            else -> result.notImplemented()
        }
    }

    private fun getPairedDevices(result: MethodChannel.Result) {
        val devices = adapter?.bondedDevices ?: emptySet()
        val list = devices.map { device ->
            mapOf(
                "name" to (device.name ?: "Unknown"),
                "address" to device.address
            )
        }
        result.success(list)
    }

    private fun connect(address: String, channel: Int?, result: MethodChannel.Result) {
        try {
            disconnect()

            val device = adapter?.getRemoteDevice(address)
            if (device == null) {
                runOnMain { result.error("NOT_FOUND", "Device not found: $address", null) }
                return
            }

            adapter?.cancelDiscovery()

            val sock = if (channel != null) {
                try {
                    Log.i(TAG, "Connecting to $address on raw channel $channel")
                    createRfcommSocket(device, channel)
                } catch (e: Exception) {
                    Log.w(TAG, "Raw channel failed, trying SDP: ${e.message}")
                    device.createRfcommSocketToServiceRecord(SPP_UUID)
                }
            } else {
                Log.i(TAG, "Connecting to $address via SDP (SPP UUID)")
                device.createRfcommSocketToServiceRecord(SPP_UUID)
            }

            sock.connect()
            socket = sock
            inputStream = sock.inputStream
            outputStream = sock.outputStream
            connected = true

            Log.i(TAG, "Connected to $address")
            val gen = ++connectionGeneration
            runOnMain { result.success(true) }

            startReadThread(gen)
            startWriteThread()
        } catch (e: IOException) {
            Log.e(TAG, "Connection failed: ${e.message}")
            connected = false
            runOnMain { result.error("CONNECT_FAILED", e.message, null) }
        }
    }

    private fun createRfcommSocket(device: BluetoothDevice, channel: Int): BluetoothSocket {
        val method = device.javaClass.getMethod("createRfcommSocket", Int::class.javaPrimitiveType)
        return method.invoke(device, channel) as BluetoothSocket
    }

    private fun startReadThread(generation: Int) {
        readThread = Thread {
            val buffer = ByteArray(4096)
            try {
                while (connected) {
                    val bytes = inputStream?.read(buffer) ?: -1
                    if (bytes <= 0) break
                    val data = buffer.copyOf(bytes)
                    runOnMain { eventSink?.success(data) }
                }
            } catch (e: IOException) {
                if (connected) {
                    Log.i(TAG, "Read error (disconnected): ${e.message}")
                }
            }
            connected = false
            // Only signal endOfStream if this is still the current connection.
            // A stale read thread must not kill a newer connection's stream.
            runOnMain {
                if (connectionGeneration == generation) {
                    eventSink?.endOfStream()
                }
            }
        }.apply {
            isDaemon = true
            name = "BT-Read"
            start()
        }
    }

    private fun startWriteThread() {
        writeThread = Thread {
            val out = outputStream ?: return@Thread
            try {
                while (connected) {
                    var wrote = false

                    // Always drain control queue first (guaranteed delivery)
                    var ctrl = controlQueue.poll()
                    while (ctrl != null) {
                        out.write(ctrl)
                        wrote = true
                        ctrl = controlQueue.poll()
                    }

                    // Then send latest state (droppable)
                    val state = pendingState.getAndSet(null)
                    if (state != null) {
                        out.write(state)
                        wrote = true
                    }

                    if (wrote) {
                        out.flush()
                    } else {
                        Thread.sleep(5)
                    }
                }
            } catch (e: IOException) {
                if (connected) {
                    Log.w(TAG, "Write error: ${e.message}")
                }
            } catch (_: InterruptedException) {}
        }.apply {
            isDaemon = true
            name = "BT-Write"
            start()
        }
    }

    fun disconnect() {
        connected = false
        connectionGeneration++  // invalidate any pending endOfStream from old read thread
        pendingState.set(null)
        controlQueue.clear()

        // Close streams/socket first so blocking read()/write() unblock
        try { inputStream?.close() } catch (_: Exception) {}
        try { outputStream?.close() } catch (_: Exception) {}
        try { socket?.close() } catch (_: Exception) {}

        // Wait for threads to exit (they'll break out due to closed streams)
        val rt = readThread
        val wt = writeThread
        readThread = null
        writeThread = null
        rt?.let {
            it.interrupt()
            try { it.join(1000) } catch (_: InterruptedException) {}
        }
        wt?.let {
            it.interrupt()
            try { it.join(1000) } catch (_: InterruptedException) {}
        }

        inputStream = null
        outputStream = null
        socket = null
    }

    private fun runOnMain(action: () -> Unit) {
        android.os.Handler(android.os.Looper.getMainLooper()).post(action)
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        eventSink = events
    }

    override fun onCancel(arguments: Any?) {
        eventSink = null
    }

    fun dispose() {
        disconnect()
    }
}
