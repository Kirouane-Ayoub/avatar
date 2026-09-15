import argparse
import io
import json
import math
import os
import struct
import time

import requests
import websocket  # pip install websocket-client

TEST_PROMPTS = [
    "Hello, how are you?",
    "What is the capital of France?",
    "Tell me a short joke.",
]


def generate_sine_wav(duration_s=2.0, sample_rate=16000, freq=440.0):
    n_samples = int(sample_rate * duration_s)
    samples = []
    for i in range(n_samples):
        sample = int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(struct.pack("<h", sample))

    audio_data = b"".join(samples)
    buf = io.BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + len(audio_data)))
    buf.write(b"WAVEfmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", len(audio_data)))
    buf.write(audio_data)
    buf.seek(0)
    return buf


def benchmark_livekit(cfg, rounds):
    """Benchmark LiveKit server: HTTP health + WebSocket connect latency."""
    lk_url = cfg.get("livekit_url", "http://localhost:7880")
    ws_url = lk_url.replace("http://", "ws://").replace("https://", "wss://")
    print("\n── LiveKit Server ──")
    print(f"   URL: {lk_url}")

    times = []

    # HTTP health check
    for i in range(rounds):
        start = time.perf_counter()
        try:
            resp = requests.get(lk_url, timeout=5)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)
            print(
                f"   [{i + 1}/{rounds}] HTTP  {elapsed:>6.1f}ms  status={resp.status_code}"
            )
        except Exception as e:
            print(f"   [{i + 1}/{rounds}] HTTP  ERROR: {e}")

    # WebSocket connect/disconnect
    ws_times = []
    for i in range(rounds):
        start = time.perf_counter()
        try:
            ws = websocket.create_connection(
                f"{ws_url}/rtc",
                timeout=5,
            )
            elapsed = (time.perf_counter() - start) * 1000
            ws.close()
            ws_times.append(elapsed)
            print(f"   [{i + 1}/{rounds}] WS    {elapsed:>6.1f}ms  connected")
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            ws_times.append(elapsed)
            # Connection refused or auth error is fine — we're measuring latency
            print(
                f"   [{i + 1}/{rounds}] WS    {elapsed:>6.1f}ms  ({type(e).__name__})"
            )

    print_stats("http", times)
    print_stats("websocket", ws_times)
    return times


def benchmark_stt(cfg, rounds):
    url = cfg["stt_url"]
    model = cfg["stt_model"]
    print("\n── STT (Faster Whisper) ──")
    print(f"   URL: {url}  Model: {model}")

    wav_bytes = generate_sine_wav(duration_s=3.0).read()
    times = []

    for i in range(rounds):
        buf = io.BytesIO(wav_bytes)
        start = time.perf_counter()
        try:
            resp = requests.post(
                f"{url}/audio/transcriptions",
                files={"file": ("test.wav", buf, "audio/wav")},
                data={"model": model},
                timeout=30,
            )
            elapsed = (time.perf_counter() - start) * 1000
            resp.raise_for_status()
            times.append(elapsed)
            text = resp.json().get("text", "")
            print(f"   [{i + 1}/{rounds}] {elapsed:>7.0f}ms  text={text!r:.40}")
        except Exception as e:
            print(f"   [{i + 1}/{rounds}] ERROR: {e}")

    return times


def benchmark_llm(cfg, rounds):
    url = cfg["llm_url"]
    model = cfg["llm_model"]
    api_key = cfg["llm_api_key"]
    print(f"\n── LLM ({model}) ──")
    print(f"   URL: {url}")

    ttfts = []
    totals = []

    for i in range(rounds):
        prompt = TEST_PROMPTS[i % len(TEST_PROMPTS)]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Reply in 1 short sentence."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 50,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {api_key}"}

        start = time.perf_counter()
        ttft = None
        full_text = ""
        token_count = 0

        try:
            # Try streaming first
            resp = requests.post(
                f"{url}/chat/completions",
                json=payload,
                headers=headers,
                stream=True,
                timeout=30,
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "):
                    continue
                data_str = decoded[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    choices = data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        if ttft is None:
                            ttft = (time.perf_counter() - start) * 1000
                        full_text += content
                        token_count += 1
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

            total = (time.perf_counter() - start) * 1000

            # Fallback: non-streaming request if streaming gave no content
            if not full_text:
                start2 = time.perf_counter()
                resp2 = requests.post(
                    f"{url}/chat/completions",
                    json={**payload, "stream": False},
                    headers=headers,
                    timeout=30,
                )
                resp2.raise_for_status()
                result = resp2.json()
                full_text = result["choices"][0]["message"].get("content", "")
                total = (time.perf_counter() - start2) * 1000
                ttft = total
                token_count = len(full_text.split())

            if ttft is None:
                ttft = total
            ttfts.append(ttft)
            totals.append(total)

            tps = token_count / (total / 1000) if total > 0 and token_count > 0 else 0
            print(
                f"   [{i + 1}/{rounds}] TTFT={ttft:>6.0f}ms  total={total:>6.0f}ms  {token_count} tok  ~{tps:.0f} tok/s  {full_text!r:.60}"
            )

        except Exception as e:
            print(f"   [{i + 1}/{rounds}] ERROR: {e}")

    return ttfts, totals


def benchmark_tts(cfg, rounds):
    url = cfg["tts_url"]
    model = cfg["tts_model"]
    voice = cfg["tts_voice"]
    print("\n── TTS (Kokoro) ──")
    print(f"   URL: {url}  Model: {model}  Voice: {voice}")

    ttfbs = []
    totals = []

    for i in range(rounds):
        text = TEST_PROMPTS[i % len(TEST_PROMPTS)]
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "pcm",
            "stream": True,
        }

        start = time.perf_counter()
        ttfb = None
        total_bytes = 0

        try:
            resp = requests.post(
                f"{url}/v1/audio/speech",
                json=payload,
                stream=True,
                timeout=30,
            )
            resp.raise_for_status()

            for chunk in resp.iter_content(chunk_size=4096):
                if chunk:
                    if ttfb is None:
                        ttfb = (time.perf_counter() - start) * 1000
                    total_bytes += len(chunk)

            total = (time.perf_counter() - start) * 1000
            audio_dur = total_bytes / (24000 * 2) * 1000  # 24kHz 16bit mono
            if ttfb:
                ttfbs.append(ttfb)
            totals.append(total)

            print(
                f"   [{i + 1}/{rounds}] TTFB={ttfb:>6.0f}ms  total={total:>6.0f}ms  audio={audio_dur:.0f}ms  {total_bytes / 1024:.0f}KB"
            )

        except Exception as e:
            print(f"   [{i + 1}/{rounds}] ERROR: {e}")

    return ttfbs, totals


def print_stats(label, values):
    if not values:
        return
    avg = sum(values) / len(values)
    mn = min(values)
    mx = max(values)
    p50 = sorted(values)[len(values) // 2]
    print(
        f"   {label:>12s}:  avg={avg:>6.0f}ms  min={mn:>6.0f}ms  max={mx:>6.0f}ms  p50={p50:>6.0f}ms"
    )


def main():
    parser = argparse.ArgumentParser(description="Benchmark voice pipeline services")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--livekit-url", default="http://localhost:7880")
    parser.add_argument("--stt-url", default="http://localhost:8000/v1")
    parser.add_argument("--tts-url", default="http://localhost:8880")
    # The LLM runs host-side (MLX), so the defaults mirror the .env variable
    # names and fall back to the local mlx_vlm.server address. Never hardcode
    # a real endpoint or key here — this file ships in the public repo.
    parser.add_argument(
        "--llm-url",
        default=os.getenv("LLM_BASE_URL", "http://localhost:8090/v1"),
    )
    parser.add_argument("--llm-api-key", default=os.getenv("LLM_API_KEY", "none"))
    parser.add_argument(
        "--llm-model",
        default=os.getenv("LLM_MODEL", "mlx-community/Qwen3.5-9B-MLX-4bit"),
    )
    parser.add_argument("--stt-model", default="Systran/faster-whisper-tiny.en")
    parser.add_argument("--tts-model", default="kokoro")
    parser.add_argument("--tts-voice", default="af_heart")
    args = parser.parse_args()

    cfg = {
        "livekit_url": args.livekit_url,
        "stt_url": args.stt_url,
        "tts_url": args.tts_url,
        "llm_url": args.llm_url,
        "llm_api_key": args.llm_api_key,
        "llm_model": args.llm_model,
        "stt_model": args.stt_model,
        "tts_model": args.tts_model,
        "tts_voice": args.tts_voice,
    }

    rounds = args.rounds
    print(f"Running benchmark with {rounds} rounds per service...\n")

    lk_times = benchmark_livekit(cfg, rounds)
    print_stats("round-trip", lk_times)

    stt_times = benchmark_stt(cfg, rounds)
    print_stats("processing", stt_times)

    llm_ttfts, llm_totals = benchmark_llm(cfg, rounds)
    print_stats("ttft", llm_ttfts)
    print_stats("total", llm_totals)

    tts_ttfbs, tts_totals = benchmark_tts(cfg, rounds)
    print_stats("ttfb", tts_ttfbs)
    print_stats("total", tts_totals)

    # Summary
    print("\n══ SUMMARY ══")
    lk_avg = sum(lk_times) / len(lk_times) if lk_times else 0
    stt_avg = sum(stt_times) / len(stt_times) if stt_times else 0
    llm_avg = sum(llm_ttfts) / len(llm_ttfts) if llm_ttfts else 0
    tts_avg = sum(tts_ttfbs) / len(tts_ttfbs) if tts_ttfbs else 0

    services = [
        ("LiveKit", lk_avg),
        ("STT", stt_avg),
        ("LLM", llm_avg),
        ("TTS", tts_avg),
    ]
    total = sum(v for _, v in services)

    bar_w = 40

    def bar(val):
        if total == 0:
            return ""
        n = round(val / total * bar_w)
        return "#" * n + "." * (bar_w - n)

    for name, avg in services:
        pct = (avg / total * 100) if total > 0 else 0
        print(f"   {name:<8s} {avg:>6.0f}ms  [{bar(avg)}]  {pct:.0f}%")
    print("   ─────────────")
    print(f"   Total    {total:>6.0f}ms")

    if total > 0:
        bottleneck = max(services, key=lambda x: x[1])
        print(
            f"\n   Bottleneck: {bottleneck[0]} ({bottleneck[1]:.0f}ms, {bottleneck[1] / total * 100:.0f}% of pipeline)"
        )


if __name__ == "__main__":
    main()
