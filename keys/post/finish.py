"""Finish the keys film: open-gate renders -> 16:9 1920x1080 and 4:5 1080x1350,
vignette, light film grain, title over the hook, audio, H.264 + AAC.

  python3 finish.py <frames_dir> <out.mp4> --aspect 169|45 [--audio mix_b12.wav]
"""
import argparse
import subprocess
from pathlib import Path

FPS = 60
W, H = 1920, 1350
HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--aspect", default="169")
    ap.add_argument("--audio", default=str(HERE.parents[1] / "build" / "mix_b14.wav"))
    ap.add_argument("--frames", type=int, default=1440)
    ap.add_argument("--x45", type=int, default=(W - 1080) // 2)
    a = ap.parse_args()
    crop = (f"crop=1920:1080:0:{(H - 1080) // 2}" if a.aspect == "169" else f"crop=1080:1350:{a.x45}:0")
    code = HERE / "code_frames" / "c_%05d.png"
    end = HERE / f"end_{a.aspect}.png"
    fc = (f"[0]scale={W}:{H}:flags=lanczos,format=rgb48le,{crop},"
          f"vignette=angle=0.5:mode=forward,noise=alls=4:allf=t+u:all_seed=77[v];"
          f"[1]format=rgba,tpad=stop_mode=add:stop=-1:color=black@0[t];"
          f"[3]format=rgba,fade=in:st=21.9:d=0.6:alpha=1[e];"
          f"[v][t]overlay=shortest=1[vt];[vt][e]overlay=shortest=1,"
          f"fade=in:st=0:d=0.5,fade=out:st=23.35:d=0.65,format=yuv420p[out]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-framerate", str(FPS), "-i", str(Path(a.src) / "f_%05d.png"),
           "-framerate", str(FPS), "-i", str(code),
           "-i", a.audio,
           "-loop", "1", "-framerate", str(FPS), "-i", str(end),
           "-filter_complex", fc, "-map", "[out]", "-map", "2:a",
           "-frames:v", str(a.frames), "-sws_flags", "spline+accurate_rnd+full_chroma_int",
           "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-profile:v", "high",
           "-x264-params", "keyint=120:min-keyint=60", "-pix_fmt", "yuv420p",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
           "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-shortest",
           "-r", str(FPS), "-movflags", "+faststart", a.dst]
    subprocess.run(cmd, check=True)
    print(a.dst)


if __name__ == "__main__":
    main()
