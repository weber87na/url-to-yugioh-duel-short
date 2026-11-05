#!/usr/bin/env python3
"""Replace a video's audio from independently editable dialogue, effects and music.

Paths are relative to the JSON file. All gains are linear (1 = unchanged).
See --help for the compact schema. Requires ffmpeg and ffprobe on PATH.
"""

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

RATE = 48000
STEMS = ("dialogue", "effects", "music")


def run(command):
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise ValueError(f"{Path(command[0]).name} failed:\n{result.stderr[-6000:]}")
    return result.stdout


def number(value, name, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be finite and between {minimum} and {maximum or 'infinity'}")
    return value


def path_value(value, base, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty path string")
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def probe(path, ffprobe, kind):
    if not path.is_file():
        raise ValueError(f"Source does not exist: {path}")
    data = json.loads(run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == kind), None)
    if stream is None:
        raise ValueError(f"Source has no {kind} stream: {path}")
    duration = stream.get("duration", data.get("format", {}).get("duration"))
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        raise ValueError(f"Cannot determine {kind} duration: {path}") from None
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Invalid {kind} duration: {path}")
    return {"duration_s": duration, "codec": stream.get("codec_name"),
            "frame_rate": stream.get("avg_frame_rate", "0/1")}


def normalize_stem(value, name, base, duration, ffprobe):
    if value is None:
        value = {}
    if isinstance(value, str):
        value = {"source": value}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a path, object, or null")
    gain = number(value.get("gain", 1), f"{name}.gain")
    source = path_value(value["source"], base, f"{name}.source") if value.get("source") is not None else None
    media = probe(source, ffprobe, "audio") if source else None
    segments = value.get("segments")
    if segments is None:
        segments = [{"source_start": 0, "output_start": 0,
                     "duration": min(duration, media["duration_s"])}] if source else []
    if not isinstance(segments, list) or (segments and not source):
        raise ValueError(f"{name}.segments must be a list and require a source")
    normalized = []
    for i, item in enumerate(segments):
        label = f"{name}.segments[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        seg = {k: number(item.get(k), f"{label}.{k}")
               for k in ("source_start", "output_start", "duration")}
        if seg["duration"] <= 0:
            raise ValueError(f"{label}.duration must be positive")
        seg.update({k: number(item.get(k, default), f"{label}.{k}")
                    for k, default in (("gain", 1), ("fade_in", 0), ("fade_out", 0))})
        if seg["source_start"] + seg["duration"] > media["duration_s"] + 1 / RATE:
            raise ValueError(f"{label} exceeds source duration {media['duration_s']:.6f}s")
        if seg["output_start"] + seg["duration"] > duration + 1 / RATE:
            raise ValueError(f"{label} exceeds output duration {duration:.6f}s")
        if seg["fade_in"] + seg["fade_out"] > seg["duration"] + 1 / RATE:
            raise ValueError(f"{label} fades exceed segment duration")
        seg["source_end"] = seg["source_start"] + seg["duration"]
        seg["output_end"] = seg["output_start"] + seg["duration"]
        seg["speed"] = 1.0
        normalized.append(seg)
    ducks = value.get("duck_intervals", [])
    if not isinstance(ducks, list) or (ducks and name != "music"):
        raise ValueError("duck_intervals is a list supported only on music")
    normalized_ducks = []
    for i, item in enumerate(ducks):
        label = f"music.duck_intervals[{i}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        duck = {k: number(item.get(k), f"{label}.{k}", maximum=duration) for k in ("start", "end")}
        if duck["end"] <= duck["start"]:
            raise ValueError(f"{label}.end must be after start")
        duck["gain"] = number(item.get("gain"), f"{label}.gain", maximum=1)
        duck.update({k: number(item.get(k, 0), f"{label}.{k}") for k in ("attack", "release")})
        normalized_ducks.append(duck)
    return {"source": str(source) if source else None, "source_media": media, "gain": gain,
            "segments": normalized, "duck_intervals": normalized_ducks}


def fmt(value):
    return format(value, ".12g")


def duck_expression(ducks):
    """Plateau [start,end]; attack/release extend outside it. Overlap uses min."""
    envelope = "1"
    for d in ducks:
        start, end, gain, attack, release = (d[k] for k in ("start", "end", "gain", "attack", "release"))
        tail = f"if(lt(t,{fmt(end + release)}),{fmt(gain)}+(1-{fmt(gain)})*(t-{fmt(end)})/{fmt(release)},1)" if release else "1"
        active = f"if(lte(t,{fmt(end)}),{fmt(gain)},{tail})"
        before = f"if(lt(t,{fmt(start - attack)}),1,1-(1-{fmt(gain)})*(t-{fmt(start - attack)})/{fmt(attack)})" if attack else "1"
        envelope = f"min({envelope},if(lt(t,{fmt(start)}),{before},{active}))"
    return envelope


def render_stem(spec, target, duration, ffmpeg):
    samples = round(duration * RATE)
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if not spec["segments"]:
        run(args + ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", fmt(samples / RATE),
                    "-c:a", "pcm_f32le", str(target)])
        return
    args += ["-i", spec["source"]]
    count = len(spec["segments"])
    filters = []
    if count > 1:
        filters.append(f"[0:a:0]asplit={count}" + "".join(f"[src{i}]" for i in range(count)))
    for i, seg in enumerate(spec["segments"]):
        source = f"src{i}" if count > 1 else "0:a:0"
        chain = ["asetpts=PTS-STARTPTS", f"atrim=start={fmt(seg['source_start'])}:end={fmt(seg['source_end'])}",
                 "asetpts=PTS-STARTPTS", "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo",
                 f"volume={fmt(seg['gain'] * spec['gain'])}"]
        if seg["fade_in"]:
            chain.append(f"afade=t=in:st=0:d={fmt(seg['fade_in'])}")
        if seg["fade_out"]:
            chain.append(f"afade=t=out:st={fmt(seg['duration'] - seg['fade_out'])}:d={fmt(seg['fade_out'])}")
        chain += [f"adelay={round(seg['output_start'] * RATE)}S:all=1", "apad", f"atrim=end_sample={samples}"]
        filters.append(f"[{source}]" + ",".join(chain) + f"[seg{i}]")
    mix = "".join(f"[seg{i}]" for i in range(count))
    mix += f"amix=inputs={count}:normalize=0:duration=longest:dropout_transition=0"
    if spec["duck_intervals"]:
        env = duck_expression(spec["duck_intervals"])
        mix += f",aeval=exprs='val(0)*({env})|val(1)*({env})':channel_layout=stereo"
    filters.append(mix + f",atrim=end_sample={samples}[out]")
    run(args + ["-filter_complex", ";".join(filters), "-map", "[out]", "-ar", str(RATE), "-ac", "2",
                "-c:a", "pcm_f32le", str(target)])


def same_path(a, b):
    if os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve())):
        return True
    return a.exists() and b.exists() and os.path.samefile(a, b)


def mix(config_path, ffmpeg, ffprobe, overwrite=False):
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError("JSON root must be an object")
    duration = number(config.get("duration_s"), "duration_s")
    if duration < 1 / RATE:
        raise ValueError("duration_s must be at least one audio sample (1/48000s)")
    base = config_path.parent
    video = path_value(config.get("video"), base, "video")
    output = path_value(config.get("output"), base, "output")
    if output.suffix.lower() not in (".mp4", ".mov", ".mkv"):
        raise ValueError("output must have .mp4, .mov, or .mkv extension")
    video_info = probe(video, ffprobe, "video")
    try:
        num, den = map(float, video_info["frame_rate"].split("/"))
        tolerance = den / num if num > 0 and den > 0 else 1 / 30
    except (ValueError, ZeroDivisionError):
        tolerance = 1 / 30
    if duration > video_info["duration_s"] + tolerance + 1e-6:
        raise ValueError(f"duration_s exceeds video duration ({video_info['duration_s']:.6f}s + one frame {tolerance:.6f}s)")
    stems = {name: normalize_stem(config.get(name), name, base, duration, ffprobe) for name in STEMS}
    stem_dir = output.parent / (output.stem + "_stems")
    stem_paths = {name: stem_dir / f"{name}.wav" for name in (*STEMS, "mix")}
    manifest_path = output.with_name(output.stem + ".mix_manifest.json")
    sources = [config_path, video] + [Path(s["source"]) for s in stems.values() if s["source"]]
    targets = [output, manifest_path, *stem_paths.values()]
    for target in targets:
        if any(same_path(target, source) for source in sources):
            raise ValueError(f"Output would overwrite a source: {target}")
        if target.exists() and (not overwrite or not target.is_file()):
            raise ValueError(f"Output already exists (use --overwrite for files): {target}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".mix-audio-", dir=output.parent) as temp:
        temporary = Path(temp)
        for name in STEMS:
            render_stem(stems[name], temporary / f"{name}.wav", duration, ffmpeg)
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        for name in STEMS:
            args += ["-i", str(temporary / f"{name}.wav")]
        limiter = "alimiter=limit=0.95:attack=5:release=50:level=false:latency=1"
        graph = f"[0:a][1:a][2:a]amix=inputs=3:normalize=0:duration=longest:dropout_transition=0,{limiter},apad,atrim=end_sample={round(duration * RATE)}[out]"
        run(args + ["-filter_complex", graph, "-map", "[out]", "-ar", str(RATE), "-ac", "2",
                    "-c:a", "pcm_f32le", str(temporary / "mix.wav")])
        mux = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(video),
               "-i", str(temporary / "mix.wav"), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-ar", str(RATE), "-ac", "2", "-t", fmt(duration)]
        if output.suffix.lower() in (".mp4", ".mov"):
            mux += ["-movflags", "+faststart"]
        run(mux + [str(temporary / output.name)])
        manifest = {
            "config": str(config_path), "duration_s": duration,
            "audio_duration_s": round(duration * RATE) / RATE,
            "video": {"source": str(video), **video_info, "mode": "stream-copy", "original_audio": "discarded"},
            "stems": stems, "output": str(output), "stem_files": {k: str(v) for k, v in stem_paths.items()},
            "stem_format": {"codec": "pcm_f32le", "sample_rate": RATE, "channels": 2,
                            "reason": "Floating-point PCM preserves headroom before the final limiter"},
            "mix": {"normalization": False, "limiter": limiter, "final_audio_codec": "aac", "bitrate": "192k"},
            "timing": {"segment_speed": 1, "overlaps": "Segments sum; only explicit fades create crossfades",
                       "duck": "Music only; gain plateau is [start,end]. Attack ramps from 1 to gain over [start-attack,start]; release ramps to 1 over [end,end+release]. Ramps extend outside the plateau and are naturally clipped by the output timeline. Overlapping ducks take the minimum envelope, not the product.",
                       "resolution": "48kHz samples; output_start rounded to nearest sample; no tempo or pitch change"}}
        (temporary / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stem_dir.mkdir(parents=True, exist_ok=True)
        for name, destination in stem_paths.items():
            os.replace(temporary / f"{name}.wav", destination)
        os.replace(temporary / output.name, output)
        os.replace(temporary / "manifest.json", manifest_path)
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''JSON schema (times in seconds, gains linear):
  {"duration_s": 3, "video": "input.mp4", "output": "result.mp4",
   "dialogue": "voice.wav", "effects": null,
   "music": {"source": "music.wav", "gain": 0.4,
     "segments": [{"source_start": 0, "output_start": 0, "duration": 3,
                   "gain": 1, "fade_in": 0.1, "fade_out": 0.2}],
     "duck_intervals": [{"start": 1, "end": 2, "gain": 0.25,
                         "attack": 0.1, "release": 0.2}]}}
Dialogue/effects accept the same source/gain/segments shape (without ducks),
a path for a timeline-aligned stem, or null. Absent stems produce silence.
Omitted segments use source time zero, trimmed/padded to duration_s.
An empty segments list produces silence. All segments play at original speed.
Ducks affect only music; attack/release extend outside [start,end].
Explicit segment fades control overlap/crossfade. No automatic normalization.
Outputs: result.mp4, result.mix_manifest.json, result_stems/{dialogue,
effects,music,mix}.wav (48kHz stereo float PCM). The final mix uses a
latency-compensated limiter; video is stream-copied and old audio discarded.''')
    parser.add_argument("config", type=Path, help="Path to the input JSON; relative media paths resolve beside it")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable (default: PATH)")
    parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe executable (default: PATH)")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output files; source files are always protected")
    args = parser.parse_args()
    try:
        for executable in (args.ffmpeg, args.ffprobe):
            if not shutil.which(executable):
                raise ValueError(f"Executable not found: {executable}")
        manifest = mix(args.config, args.ffmpeg, args.ffprobe, args.overwrite)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Mix completed. Manifest: {manifest}")


if __name__ == "__main__":
    main()
