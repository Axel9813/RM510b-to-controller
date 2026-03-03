package com.dji.rc_to_controller

data class RcState(
    val seq: Int = 0,
    val stickRightH: Int = 0,
    val stickRightV: Int = 0,
    val stickLeftV: Int = 0,
    val stickLeftH: Int = 0,
    val leftWheel: Int = 0,
    val rightWheel: Int = 0,
    val record: Boolean = false,
    val shutter: Boolean = false,
    val fiveDUp: Boolean = false,
    val fiveDDown: Boolean = false,
    val fiveDLeft: Boolean = false,
    val fiveDRight: Boolean = false,
    val fiveDCenter: Boolean = false
) {
    fun toMap(): Map<String, Any> = mapOf(
        "seq" to seq,
        "stickRightH" to stickRightH,
        "stickRightV" to stickRightV,
        "stickLeftV" to stickLeftV,
        "stickLeftH" to stickLeftH,
        "leftWheel" to leftWheel,
        "rightWheel" to rightWheel,
        "record" to record,
        "shutter" to shutter,
        "fiveDUp" to fiveDUp,
        "fiveDDown" to fiveDDown,
        "fiveDLeft" to fiveDLeft,
        "fiveDRight" to fiveDRight,
        "fiveDCenter" to fiveDCenter
    )

    companion object {
        /** Parse 18-byte HID packet into RcState. Returns null if packet is invalid. */
        fun fromHidPacket(data: ByteArray): RcState? {
            if (data.size < 18) return null
            if (data[0] != 0x02.toByte() || data[1] != 0x0E.toByte()) return null

            fun uint16LE(offset: Int): Int =
                (data[offset].toInt() and 0xFF) or ((data[offset + 1].toInt() and 0xFF) shl 8)

            val seq = uint16LE(2)
            val leftH = uint16LE(4) - 1024
            val leftV = uint16LE(6) - 1024
            val rightH = uint16LE(8) - 1024
            val rightV = uint16LE(10) - 1024
            val lWheel = uint16LE(12) - 1024
            val rWheel = uint16LE(14) - 1024

            val b16 = data[16].toInt() and 0xFF
            val b17 = data[17].toInt() and 0xFF

            return RcState(
                seq = seq,
                stickRightH = rightH,
                stickRightV = rightV,
                stickLeftV = leftV,
                stickLeftH = leftH,
                leftWheel = lWheel,
                rightWheel = rWheel,
                record = (b16 and 0x04) != 0,
                shutter = (b16 and 0x08) != 0,
                fiveDUp = (b17 and 0x01) != 0,
                fiveDDown = (b17 and 0x02) != 0,
                fiveDLeft = (b17 and 0x04) != 0,
                fiveDRight = (b17 and 0x08) != 0,
                fiveDCenter = (b17 and 0x10) != 0
            )
        }
    }
}
