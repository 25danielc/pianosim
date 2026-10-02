"""Finishing: open-gate 1920x1350 renders -> 16:9 (1920x1080) and 4:5 (1080x1350)
crops with vignette + light film grain (+ optional title overlay and audio).

  stills:  python3 finish.py stills <in_dir> <out_dir>
  video:   python3 finish.py video <frames_dir> <out.mp4> --aspect 169|45 [--from F --to F] [--audio mix.wav]

The 4:5 window's horizontal position comes from each shot's `crop45` (0..1),
passed in as a per-frame table (crop45.txt: "frame x_offset" lines).
"""
import argparse
import subprocess
import sys
from pathlib import Path

W, H = 1920, 1350
GRAIN = "noise=alls=5:allf=t+u:all_seed=1234"


def crop_filter(aspect, x45=420):
    if aspect == "169":
        return f"crop=1920:1080:0:{(H - 1080) // 2}"
    return f"crop=1080:1350:{x45}:0"


def look_filter(aspect):
    # vignette around each crop's own centre; grain after the vignette;
    # error-diffusion dither down to 8 bit so the haze gradients don't band
    return ("format=rgb48le,vignette=angle=0.55:mode=forward,"
            + GRAIN + ",format=rgb24")


def stills(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.png")):
        for aspect in ("169", "45"):
            out = dst / f"{f.stem}_{aspect}.png"
            vf = crop_filter(aspect) + "," + look_filter(aspect)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(f), "-vf", vf,
                            "-sws_dither", "ed", str(out)], check=True)
            print(out)


def video(src, dst, aspect, f0, f1, audio):
    n = f1 - f0
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-start_number", str(f0),
           "-i", str(src / "f_%05d.png")]
    title = Path(__file__).parent / f"title_{aspect}.png"
    cmd += ["-loop", "1", "-framerate", "30", "-i", str(title)]
    if audio:
        cmd += ["-ss", f"{f0 / 30:.6f}", "-t", f"{n / 30:.6f}", "-i", str(audio)]
    t0 = f0 / 30
    # title: fades in at 0.35 s, out by 4.3 s (video time); offset for partial renders
    fc = (f"[0]{crop_filter(aspect)},{look_filter(aspect)}[v];"
          f"[1]format=rgba,fade=in:st={0.35 - t0:.3f}:d=0.5:alpha=1,fade=out:st={3.7 - t0:.3f}:d=0.6:alpha=1[t];"
          f"[v][t]overlay=shortest=1,format=yuv420p[out]")
    cmd += ["-frames:v", str(n), "-filter_complex", fc, "-map", "[out]",
            "-sws_flags", "spline+accurate_rnd+full_chroma_int",
            "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high",
            "-x264-params", "keyint=60:min-keyint=30", "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if audio:
        cmd += ["-map", "2:a", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest"]
    cmd += ["-r", "30", "-movflags", "+faststart", str(dst)]
    subprocess.run(cmd, check=True)
    print(dst)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--aspect", default="169")
    ap.add_argument("--from", dest="f0", type=int, default=0)
    ap.add_argument("--to", dest="f1", type=int, default=2730)
    ap.add_argument("--audio", default="")
    a = ap.parse_args()
    if a.mode == "stills":
        stills(Path(a.src), Path(a.dst))
    else:
        video(Path(a.src), Path(a.dst), a.aspect, a.f0, a.f1, a.audio)
