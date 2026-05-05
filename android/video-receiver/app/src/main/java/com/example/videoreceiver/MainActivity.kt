package com.example.videoreceiver

import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Bundle
import android.util.Log
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private lateinit var surfaceView: SurfaceView
    private var decoder: MediaCodec? = null

    companion object {
        private const val TAG = "VideoReceiver"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContentView(R.layout.activity_main)
        surfaceView = findViewById(R.id.surfaceView)

        surfaceView.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) {
                startDecoder(holder.surface)

                Thread {
                    try {
                        val bytes = assets.open("test.h264").readBytes()
                        val nalUnits = splitAnnexBNalUnits(bytes)

                        Log.d(TAG, "total bytes = ${bytes.size}")
                        Log.d(TAG, "NAL count = ${nalUnits.size}")

                        for ((index, nal) in nalUnits.withIndex()) {
                            logNalInfo(index, nal)
                            feedDecoder(nal)
                            Thread.sleep(33) // 30fps 기준
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "decoder thread failed", e)
                    }
                }.start()
            }

            override fun surfaceChanged(
                holder: SurfaceHolder,
                format: Int,
                width: Int,
                height: Int
            ) {
                Log.d(TAG, "Surface changed: ${width}x$height")
            }

            override fun surfaceDestroyed(holder: SurfaceHolder) {
                stopDecoder()
            }
        })
    }

    private fun startDecoder(surface: Surface) {
        if (decoder != null) return

        val mimeType = "video/avc"//Android에서 H.264/AVC 디코더를 요청
        val width = 1280
        val height = 720

        val format = MediaFormat.createVideoFormat(mimeType, width, height)

        decoder = MediaCodec.createDecoderByType(mimeType).apply {
            configure(format, surface, null, 0)
            start()
        }

        Log.d(TAG, "H.264 decoder started: ${width}x$height")
    }

    private fun stopDecoder() {
        decoder?.let {
            try {
                it.stop()
                it.release()
            } catch (e: Exception) {
                Log.e(TAG, "stopDecoder failed", e)
            }
        }

        decoder = null
        Log.d(TAG, "H.264 decoder stopped")
    }

    private fun feedDecoder(data: ByteArray) {
        val codec = decoder ?: return

        val inputIndex = codec.dequeueInputBuffer(10000)

        if (inputIndex >= 0) {
            val inputBuffer = codec.getInputBuffer(inputIndex)
            inputBuffer?.clear()

            if (inputBuffer == null || data.size > inputBuffer.capacity()) {
                Log.e(TAG, "input buffer too small. data=${data.size}, capacity=${inputBuffer?.capacity()}")
                return
            }

            inputBuffer.put(data)

            codec.queueInputBuffer(
                inputIndex,
                0,
                data.size,
                System.nanoTime() / 1000,
                0
            )
        }

        val bufferInfo = MediaCodec.BufferInfo()
        var outputIndex = codec.dequeueOutputBuffer(bufferInfo, 10000)

        while (outputIndex >= 0) {
            Log.d(TAG, "output frame: size=${bufferInfo.size}, pts=${bufferInfo.presentationTimeUs}")
            codec.releaseOutputBuffer(outputIndex, true)
            outputIndex = codec.dequeueOutputBuffer(bufferInfo, 0)
        }
    }

    private fun splitAnnexBNalUnits(data: ByteArray): List<ByteArray> {
        val startCodes = mutableListOf<Int>()

        var i = 0
        while (i < data.size - 3) {
            val startCodeLength = getStartCodeLength(data, i)
            if (startCodeLength > 0) {
                startCodes.add(i)
                i += startCodeLength
            } else {
                i++
            }
        }

        val nalUnits = mutableListOf<ByteArray>()

        for (idx in startCodes.indices) {
            val start = startCodes[idx]
            val end = if (idx + 1 < startCodes.size) startCodes[idx + 1] else data.size

            if (end > start) {
                nalUnits.add(data.copyOfRange(start, end))
            }
        }

        return nalUnits
    }

    private fun getStartCodeLength(data: ByteArray, offset: Int): Int {
        if (
            offset + 3 < data.size &&
            data[offset] == 0.toByte() &&
            data[offset + 1] == 0.toByte() &&
            data[offset + 2] == 0.toByte() &&
            data[offset + 3] == 1.toByte()
        ) {
            return 4
        }

        if (
            offset + 2 < data.size &&
            data[offset] == 0.toByte() &&
            data[offset + 1] == 0.toByte() &&
            data[offset + 2] == 1.toByte()
        ) {
            return 3
        }

        return 0
    }

    private fun logNalInfo(index: Int, nal: ByteArray) {
        val startCodeLength = getStartCodeLength(nal, 0)

        if (startCodeLength <= 0 || nal.size <= startCodeLength) {
            Log.d(TAG, "NAL[$index] invalid, size=${nal.size}")
            return
        }

        val nalHeader = nal[startCodeLength].toInt() and 0xFF
        val nalType = nalHeader and 0x1F

        val typeName = when (nalType) {
            1 -> "non-IDR slice / P-frame"
            5 -> "IDR slice / key frame"
            6 -> "SEI"
            7 -> "SPS"
            8 -> "PPS"
            9 -> "AUD"
            else -> "other"
        }

        Log.d(TAG, "NAL[$index]: type=$nalType ($typeName), size=${nal.size}")
    }
}