package com.example.videoreceiver

import android.media.MediaCodec
import android.media.MediaFormat
import android.os.Bundle
import android.util.Log
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import androidx.appcompat.app.AppCompatActivity
import java.io.ByteArrayOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetSocketAddress
import java.net.SocketTimeoutException

class MainActivity : AppCompatActivity() {

    private lateinit var surfaceView: SurfaceView
    private var decoder: MediaCodec? = null

    @Volatile
    private var receiving = false
    private var receiverThread: Thread? = null

    companion object {
        private const val TAG = "VideoReceiver"

        // Video transport: raw H.264 Annex-B byte stream over UDP (NOT RTP).
        // The Head Pi sender (head_h264_sender.py) splits the encoder output into
        // ~1200B UDP datagrams with no framing, so the receiver must accumulate
        // bytes and re-split on Annex-B start codes — datagram boundaries are NOT
        // frame/NAL boundaries.
        private const val DEFAULT_VIDEO_PORT = 5001
        private const val UDP_RECV_BUFFER_SIZE = 65536
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContentView(R.layout.activity_main)
        surfaceView = findViewById(R.id.surfaceView)

        surfaceView.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) {
                startDecoder(holder.surface)

                // Live path: receive raw H.264 Annex-B over UDP from the Head Pi.
                // To play the bundled assets/test.h264 instead (offline test),
                // call runAssetTestPlayback() here instead of startUdpReceiver().
                startUdpReceiver(DEFAULT_VIDEO_PORT)
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
                stopUdpReceiver()
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

    private fun startUdpReceiver(port: Int) {
        if (receiving) return
        receiving = true

        receiverThread = Thread {
            var socket: DatagramSocket? = null
            try {
                socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    bind(InetSocketAddress(port))
                    soTimeout = 1000
                }

                Log.d(TAG, "UDP receiver listening on :$port (raw H.264 Annex-B over UDP)")

                val packet = DatagramPacket(ByteArray(UDP_RECV_BUFFER_SIZE), UDP_RECV_BUFFER_SIZE)
                val stream = ByteArrayOutputStream()

                while (receiving) {
                    try {
                        socket.receive(packet)
                    } catch (e: SocketTimeoutException) {
                        continue
                    }

                    // Datagram boundaries are NOT NAL boundaries: accumulate, then
                    // re-split on Annex-B start codes.
                    stream.write(packet.data, packet.offset, packet.length)

                    val buffered = stream.toByteArray()
                    val consumed = drainNalUnits(buffered)

                    if (consumed > 0) {
                        stream.reset()
                        if (consumed < buffered.size) {
                            stream.write(buffered, consumed, buffered.size - consumed)
                        }
                    }
                }
            } catch (e: Exception) {
                if (receiving) {
                    Log.e(TAG, "UDP receiver failed", e)
                }
            } finally {
                socket?.close()
                Log.d(TAG, "UDP receiver stopped")
            }
        }.also { it.start() }
    }

    private fun stopUdpReceiver() {
        receiving = false
        receiverThread?.interrupt()
        receiverThread = null
    }

    // Feeds every complete NAL unit found in the accumulated buffer and returns
    // the number of leading bytes consumed. The trailing (possibly incomplete)
    // NAL unit — everything from the last start code onward — is left for the
    // next datagram.
    private fun drainNalUnits(data: ByteArray): Int {
        val starts = mutableListOf<Int>()

        var i = 0
        while (i < data.size) {
            val startCodeLength = getStartCodeLength(data, i)
            if (startCodeLength > 0) {
                starts.add(i)
                i += startCodeLength
            } else {
                i++
            }
        }

        // Need a following start code to know where the current NAL ends.
        if (starts.size < 2) return 0

        for (idx in 0 until starts.size - 1) {
            val start = starts[idx]
            val end = starts[idx + 1]
            feedDecoder(data.copyOfRange(start, end))
        }

        return starts.last()
    }

    // Offline test path: decode the bundled assets/test.h264 instead of the
    // network stream. Not used in the live UDP path; kept for debugging.
    private fun runAssetTestPlayback() {
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
                Log.e(TAG, "asset playback thread failed", e)
            }
        }.start()
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