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
import java.nio.ByteBuffer
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {

    private lateinit var surfaceView: SurfaceView
    private var decoder: MediaCodec? = null

    @Volatile
    private var running = false
    private var receiverThread: Thread? = null
    private var decodeThread: Thread? = null

    // Decoupling buffer between the network thread and the decode thread.
    // The receiver only ever reads the socket and pushes complete NAL units
    // here; the decode thread owns MediaCodec. This keeps the socket drained
    // even when the decoder blocks, which is what previously caused datagram
    // loss (and therefore corrupted, never-rendering streams).
    private val nalQueue = LinkedBlockingQueue<ByteArray>(QUEUE_CAPACITY)

    // Monotonic presentation timestamp, advanced once per coded picture.
    private var ptsUs = 0L

    companion object {
        private const val TAG = "VideoReceiver"

        // Video transport: raw H.264 Annex-B byte stream over UDP (NOT RTP).
        // The Head Pi sender (head_h264_sender.py) splits the encoder output into
        // ~1200B UDP datagrams with no framing, so the receiver must accumulate
        // bytes and re-split on Annex-B start codes — datagram boundaries are NOT
        // frame/NAL boundaries.
        private const val DEFAULT_VIDEO_PORT = 5001
        private const val UDP_RECV_BUFFER_SIZE = 65536

        private const val MIME_TYPE = "video/avc"
        private const val VIDEO_WIDTH = 1280
        private const val VIDEO_HEIGHT = 720
        private const val VIDEO_FPS = 30

        // Bounded so a stalled decoder can never exhaust memory; on overflow we
        // drop the OLDEST queued NAL (the freshest data is the most useful).
        private const val QUEUE_CAPACITY = 1024

        // H.264 NAL unit types (nal_unit_type, header byte & 0x1F).
        private const val NAL_TYPE_NON_IDR = 1
        private const val NAL_TYPE_IDR = 5
        private const val NAL_TYPE_SPS = 7
        private const val NAL_TYPE_PPS = 8
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContentView(R.layout.activity_main)
        surfaceView = findViewById(R.id.surfaceView)

        surfaceView.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) {
                running = true

                // The decoder is configured lazily by the decode thread once the
                // first SPS+PPS arrive (so it can be configured with codec-specific
                // data). Start the decode thread first, then the receiver.
                startDecodeThread(holder.surface)

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
                stopAll()
            }
        })
    }

    // =========================================================================
    // Receiver thread: socket -> NAL queue (never touches MediaCodec)
    // =========================================================================

    private fun startUdpReceiver(port: Int) {
        if (receiverThread != null) return

        receiverThread = Thread {
            var socket: DatagramSocket? = null
            try {
                socket = DatagramSocket(null).apply {
                    reuseAddress = true
                    bind(InetSocketAddress(port))
                    soTimeout = 1000
                    // A generous OS receive buffer absorbs bursts (large I-frames
                    // arrive as many back-to-back ~1200B datagrams).
                    receiveBufferSize = 1 shl 20
                }

                Log.d(TAG, "UDP receiver listening on :$port (raw H.264 Annex-B over UDP)")

                val packet = DatagramPacket(ByteArray(UDP_RECV_BUFFER_SIZE), UDP_RECV_BUFFER_SIZE)
                val stream = ByteArrayOutputStream()

                while (running) {
                    try {
                        socket.receive(packet)
                    } catch (e: SocketTimeoutException) {
                        continue
                    }

                    // Datagram boundaries are NOT NAL boundaries: accumulate, then
                    // re-split on Annex-B start codes and enqueue complete NALs.
                    stream.write(packet.data, packet.offset, packet.length)

                    val buffered = stream.toByteArray()
                    val consumed = drainNalUnitsToQueue(buffered)

                    if (consumed > 0) {
                        stream.reset()
                        if (consumed < buffered.size) {
                            stream.write(buffered, consumed, buffered.size - consumed)
                        }
                    }
                }
            } catch (e: Exception) {
                if (running) {
                    Log.e(TAG, "UDP receiver failed", e)
                }
            } finally {
                socket?.close()
                Log.d(TAG, "UDP receiver stopped")
            }
        }.also { it.start() }
    }

    // Splits every complete NAL unit out of the accumulated buffer and enqueues
    // it. Returns the number of leading bytes consumed. The trailing (possibly
    // incomplete) NAL — everything from the last start code onward — is left for
    // the next datagram.
    private fun drainNalUnitsToQueue(data: ByteArray): Int {
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
            enqueueNal(data.copyOfRange(starts[idx], starts[idx + 1]))
        }

        return starts.last()
    }

    private fun enqueueNal(nal: ByteArray) {
        // Drop the oldest if the decoder has fallen behind, so the queue can
        // never grow without bound. Fresh data is preferred over stale.
        if (!nalQueue.offer(nal)) {
            nalQueue.poll()
            nalQueue.offer(nal)
        }
    }

    // =========================================================================
    // Decode thread: NAL queue -> MediaCodec (owns the decoder)
    // =========================================================================

    private fun startDecodeThread(surface: Surface) {
        if (decodeThread != null) return

        decodeThread = Thread {
            try {
                decodeLoop(surface)
            } catch (e: Exception) {
                if (running) {
                    Log.e(TAG, "decode thread failed", e)
                }
            } finally {
                stopDecoder()
            }
        }.also { it.start() }
    }

    private fun decodeLoop(surface: Surface) {
        // Phase 1: collect codec-specific data (SPS + PPS) before configuring.
        var sps: ByteArray? = null
        var pps: ByteArray? = null

        while (running && (sps == null || pps == null)) {
            val nal = nalQueue.poll(500, TimeUnit.MILLISECONDS) ?: continue
            when (nalType(nal)) {
                NAL_TYPE_SPS -> sps = nal
                NAL_TYPE_PPS -> pps = nal
            }
        }

        val spsNal = sps ?: return
        val ppsNal = pps ?: return

        // Phase 2: configure the decoder WITH the parameter sets. csd-0/csd-1
        // take the Annex-B SPS/PPS (start code included), which is exactly what
        // we captured above.
        val format = MediaFormat.createVideoFormat(MIME_TYPE, VIDEO_WIDTH, VIDEO_HEIGHT).apply {
            setByteBuffer("csd-0", ByteBuffer.wrap(spsNal))
            setByteBuffer("csd-1", ByteBuffer.wrap(ppsNal))
        }

        val codec = MediaCodec.createDecoderByType(MIME_TYPE).apply {
            configure(format, surface, null, 0)
            start()
        }
        decoder = codec
        Log.d(TAG, "H.264 decoder configured with in-stream SPS/PPS: ${VIDEO_WIDTH}x$VIDEO_HEIGHT")

        // Phase 3: feed NALs. Skip delta frames until the first IDR so the
        // decoder always starts from a clean keyframe.
        val bufferInfo = MediaCodec.BufferInfo()
        var sawKeyFrame = false

        while (running) {
            val nal = nalQueue.poll(500, TimeUnit.MILLISECONDS)
            if (nal == null) {
                drainOutput(codec, bufferInfo)
                continue
            }

            val type = nalType(nal)
            if (!sawKeyFrame) {
                when (type) {
                    NAL_TYPE_IDR -> sawKeyFrame = true
                    NAL_TYPE_SPS, NAL_TYPE_PPS -> { /* fall through and feed */ }
                    else -> continue // drop P-frames that precede the first IDR
                }
            }

            // Feed with retry: if no input buffer is free right now, keep
            // draining output and try again rather than DROPPING the NAL (a
            // dropped SPS/PPS/IDR would stall decoding indefinitely).
            while (running && !feedNal(codec, nal, type)) {
                drainOutput(codec, bufferInfo)
            }
            drainOutput(codec, bufferInfo)
        }
    }

    // Submits one NAL to the decoder. Returns false if no input buffer was
    // available (caller should retry), true once the NAL has been handled.
    private fun feedNal(codec: MediaCodec, nal: ByteArray, type: Int): Boolean {
        val inputIndex = codec.dequeueInputBuffer(10000)
        if (inputIndex < 0) return false

        val inputBuffer = codec.getInputBuffer(inputIndex)
        if (inputBuffer == null) {
            // Hand the buffer back so it is not leaked.
            codec.queueInputBuffer(inputIndex, 0, 0, 0, 0)
            return true
        }

        if (nal.size > inputBuffer.capacity()) {
            // Should not happen for 720p/1Mbps, but never overflow the buffer.
            Log.e(TAG, "NAL too large: ${nal.size} > ${inputBuffer.capacity()}, skipping")
            codec.queueInputBuffer(inputIndex, 0, 0, 0, 0)
            return true
        }

        inputBuffer.clear()
        inputBuffer.put(nal)

        val isConfig = type == NAL_TYPE_SPS || type == NAL_TYPE_PPS
        val flags = if (isConfig) MediaCodec.BUFFER_FLAG_CODEC_CONFIG else 0
        val pts = if (isConfig) 0L else ptsUs

        // Advance the clock once per coded picture (slice NALs).
        if (type == NAL_TYPE_IDR || type == NAL_TYPE_NON_IDR) {
            ptsUs += 1_000_000L / VIDEO_FPS
        }

        codec.queueInputBuffer(inputIndex, 0, nal.size, pts, flags)
        return true
    }

    private fun drainOutput(codec: MediaCodec, bufferInfo: MediaCodec.BufferInfo) {
        var outputIndex = codec.dequeueOutputBuffer(bufferInfo, 0)
        while (outputIndex >= 0) {
            codec.releaseOutputBuffer(outputIndex, true)
            outputIndex = codec.dequeueOutputBuffer(bufferInfo, 0)
        }
    }

    // =========================================================================
    // Lifecycle / teardown
    // =========================================================================

    private fun stopAll() {
        running = false

        receiverThread?.interrupt()
        receiverThread = null

        decodeThread?.interrupt()
        decodeThread = null

        nalQueue.clear()
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

    // =========================================================================
    // Offline test path (decode the bundled assets/test.h264, no network)
    // =========================================================================

    // Not used in the live UDP path; kept for debugging. Routes the asset
    // through the SAME decode thread (queue -> SPS/PPS config -> IDR gate), so
    // it exercises the real decode path.
    private fun runAssetTestPlayback(surface: Surface) {
        running = true
        startDecodeThread(surface)

        Thread {
            try {
                val bytes = assets.open("test.h264").readBytes()
                val nalUnits = splitAnnexBNalUnits(bytes)

                Log.d(TAG, "total bytes = ${bytes.size}")
                Log.d(TAG, "NAL count = ${nalUnits.size}")

                for ((index, nal) in nalUnits.withIndex()) {
                    logNalInfo(index, nal)
                    enqueueNal(nal)
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

    // Returns the nal_unit_type, or -1 if this byte array does not begin with a
    // valid Annex-B start code.
    private fun nalType(nal: ByteArray): Int {
        val startCodeLength = getStartCodeLength(nal, 0)
        if (startCodeLength <= 0 || nal.size <= startCodeLength) return -1
        return nal[startCodeLength].toInt() and 0x1F
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
        val nalTypeValue = nalHeader and 0x1F

        val typeName = when (nalTypeValue) {
            1 -> "non-IDR slice / P-frame"
            5 -> "IDR slice / key frame"
            6 -> "SEI"
            7 -> "SPS"
            8 -> "PPS"
            9 -> "AUD"
            else -> "other"
        }

        Log.d(TAG, "NAL[$index]: type=$nalTypeValue ($typeName), size=${nal.size}")
    }
}
