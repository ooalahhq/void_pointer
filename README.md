# Void Pointer: Last Light — Pixel Art + SFX MVP

Two-player local keyboard prototype in Python + Pygame. Original procedural sound effects and original pixel art graphics included (no Undertale assets).

## Setup (Arch Linux / Linux / Windows)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python main.py
```

For the hand-controlled game, install the camera dependencies once:

```bash
.venv/bin/python -m pip install -r requirements-hand.txt
.venv/bin/python main.py
```

The model in `assets/models/hand_landmarker.task` is reused from the Jarvis template. If it is missing, run `.venv/bin/python scripts/download_hand_model.py` once to download the official model. Use `--camera 1` to select another webcam or `--model /absolute/path/hand_landmarker.task` to select a model. Keyboard-only play needs only `requirements.txt`: `.venv/bin/python main.py --no-camera`.

### iPhone camera without OBS

Open **DroidCam Webcam & OBS Camera** on the iPhone and allow camera/local-network access. Keep the app in the foreground and the iPhone and computer on the same Wi-Fi. Read the phone's Wi-Fi IP from the app, then use its HTTP video endpoint directly:

```bash
.venv/bin/python main.py --camera-url 'http://192.168.1.50:4747/video'
```

Replace the example IP and port with the ones shown by your app. The `/video` endpoint is documented in [DroidCam Help](https://droidcam.app/help/#remote-controls). This route does not need OBS, a DroidCam desktop client, or a virtual-camera kernel module. A web page or VDO.Ninja view link is not a direct video stream URL. `--camera-url` also accepts an RTSP stream supported by OpenCV/FFmpeg. Network open/read timeouts allow reconnection after disconnects. Start with landscape video and 30 FPS.

If using Tailscale, both devices must be connected to the same tailnet and the phone's video service must be reachable through its Tailscale address. Do not assume local Wi-Fi discovery will work over the VPN; first verify the video URL from the computer. Local Wi-Fi is the simplest first test.

## Controls

- P1 cyan: **W A S D**
- P2 violet: **arrow keys**
- **R** restart, **Esc** exit
- **Space / Enter** skip the opening cinematic
- **H** switch between hand control and keyboard (camera releases while paused)
- **C** start/cancel two-player hand calibration during gameplay (pauses the fight)
- **K** rebind hand ownership; show P1 on the mirrored left and P2 on the right
- **T** show/hide the mirrored camera preview and hand landmarks

## Hand controls

Show one hand per player: initially **P1 to the mirrored left of P2**. Both can use the same handedness; detector list order does not decide ownership. Two visible hands are acquired in left-to-right order even if both palms lie on the same side of the camera center. Initially point with the index finger alone to arm gestures. The fingertip crosshair is the target, and the player follows it at the normal movement speed. Each player's comfortable camera region maps independently to the entire arena; camera capture and inference run on a background thread.

| Gesture | Skill |
| --- | --- |
| Thumb + index pinch | Dash in the last movement direction |
| Open palm held steady for 0.3 seconds | Shield |
| V sign (index + middle; ring + pinky curled), held briefly | Pulse |

Gestures fire once per pose; release before trying again. Cooldowns still apply. On tracking loss, the player stops following the pointer and no new gesture fires. Show a neutral pointing pose again to rearm after a dropout, mode switch, restart, or calibration. Use **H** if the camera is unavailable; keyboard skill buttons are enabled in keyboard mode.

For calibration, press **C**, then each player points at the comfortable top-left extent of their hand range and pinches, releases, then repeats at the bottom-right extent. The on-screen diagram shows fingertip positions in the mirrored camera. Tiny calibration ranges are rejected. Calibration remains in memory for restarts and mode changes, and resets when the app is relaunched.

One MediaPipe tracker now sees the entire camera image at 640×480. Hand ownership uses palm positions and soft motion matching; fast movement and crossing the camera center do not discard detections. With two visible hands, both detections are always assigned. Short dropouts hold the last crosshair/filter for 0.25 seconds with a HOLD indicator while player motion freezes and unfinished gestures are cancelled. They preserve the acquired hand state; release a held gesture before starting a new skill. Longer dropouts show SHOW HAND. The footer includes tracking FPS. Stale inference frames expire after 0.65 seconds. Fully overlapping hands can remain ambiguous; K reacquires ownership.

A small mirrored camera preview shows the actual frame and detected skeletons: cyan for P1, violet for P2. Its hand count helps distinguish a camera detection miss from an ownership problem. Press T to hide it. Images are kept only in memory and are never saved or transmitted.

## Player skills

| Skill | P1 | P2 | Effect | Cooldown |
| --- | --- | --- | --- | --- |
| Dash | E | Right Ctrl | Dash in the last movement direction for 0.16 seconds; brief invulnerability | 4 seconds |
| Shield | Q | Right Shift | Block damage for 1.2 seconds | 10 seconds |
| Pulse | F | Enter | Clear projectiles within 150 pixels; lasers remain active | 12 seconds |

Skills work during boss fights and the final duel. HUD indicators show READY or remaining cooldown. Restart resets skills. Healing cannot revive a dead player.

### Input architecture

The input-independent `activate_skill(state, player, action)` function accepts `dash`, `shield`, or `pulse`. Keyboard and `hand_control/` both call this entry point. Tracker, gesture interpreter, index-tip measurement, pointer filter, and latest-sample mailbox were adapted from `/home/ucup/FREELANCE/jarvis/tools/ironman_file_explorer/` and are local to this project; the game does not import or modify Jarvis at runtime.

Configuration lives in `hand_control/config.py`. The tracker uses one MediaPipe Hand Landmarker Tasks instance in `VIDEO` mode with `num_hands=2`, publishes landmark measurements and an optional small camera preview into one latest-frame mailbox, and does not block the game loop. Reference: [official Hand Landmarker Python guide](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python).

## Opening cinematic

The window is 1280×800. Before the first battle, a 6.2-second title sequence reveals **VOID POINTER [LAST LIGHT]** with converging light particles, a light sweep, letterbox bars, and a fade into the arena. Gameplay timers stay paused during the intro. Restart goes straight into a fresh battle. The title is shown in the intro instead of the in-game HUD.

Combat now includes glowing explosion particles, expanding shockwaves, dash afterimages, projectile trails, shield impact sparks, healing bursts, and a larger explosion when the Warden falls. Arena shake varies by impact strength and fades quickly; the HUD remains stationary. Particle and shockwave counts are capped, and visual randomness is separate from gameplay randomness.

## Rules

Each player starts with 3 HP. Collect the golden sword by touching it, then touch The Warden to deal 1 damage. Sword is consumed on hit; another sword spawns. Avoid incoming projectiles. Boss has 8 HP. When defeated, if both players remain and have equal HP, a final sudden-death laser duel starts (warning lines before every beam); last survivor wins. Otherwise the surviving player or player with higher HP wins. Simultaneous laser death is resolved by boss damage contribution, or a draw if tied.

## Boss attacks

During the boss fight, a green healing orb with a plus sign appears at a random location: first after 8–12 seconds, then every 10–16 seconds. Touch it to recover 1 HP (maximum 3). Players at full HP leave the orb available; dead players cannot collect it. Only one healing orb can exist at a time, and it disappears after 8 seconds. Healing stops when the boss fight ends. Spawn locations avoid players, the Warden, the sword, nearby projectiles, and existing laser lanes at spawn time.

- **HUNT (8–6 HP):** aimed single orbs, with a short opening grace period.
- **BARRAGE (5–3 HP):** three-orb fans and targeted lasers. Laser warning lasts 1.1 seconds before dealing normal damage.
- **LAST LIGHT (2–1 HP):** alternates five-orb fans with circular bursts. A red charge ring warns 0.8 seconds before a burst.

Stage changes clear existing hazards and give players time to reposition. Sword hits show an animated slash, sparks, and a boss flash. Attacking still happens automatically when a sword carrier touches the boss. If the carrier dies, a new sword spawns for surviving players.

The Warden roams between random points within the arena. Its speed changes abruptly between slow movement (65–110 pixels/second for 1–2.2 seconds) and fast bursts (290–380 pixels/second for 0.45–0.95 seconds). Projectiles, burst warnings, sword collisions, and sword spawn positions follow its current location. Movement resets when you press R.

## Backsound

Isi `BACKSOUND_PATH` di `main.py` dengan absolute path file audio kamu, misalnya `'/home/ucup/Music/backsound.ogg'`. Kosongkan string untuk menonaktifkan backsound. Musik diputar berulang; atur volumenya lewat `BACKSOUND_VOLUME` (0.0–1.0). Jika file gagal dimuat, game tetap berjalan dengan SFX yang tersedia.

## Included assets

`assets/sprites/warden_0.png` through `warden_2.png` are hand-made procedural pixel art frames; `sword.png` is a simple pickup. `assets/sfx/` contains nine original synthesized WAVs. Source game is `main.py` (kept small for early MVP). Sound uses pygame.mixer and is disabled gracefully if no audio output device exists.

## Next work

Live two-player camera playtesting, gesture threshold tuning, and latency evaluation. Keyboard gameplay and actual audio output still need interactive playtesting. Automated checks use dummy SDL display/audio drivers and synthetic hand frames:

```bash
.venv/bin/python -m unittest discover -s tests -v
```
