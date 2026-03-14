import eventlet
eventlet.monkey_patch()

from flask import Flask, request
from flask_socketio import SocketIO, emit
import math, random, time, threading

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

WALLS = [
  (0,0,3000,32),(0,2968,3000,32),(0,0,32,3000),(2968,0,32,3000),
  (200,400,600,32),(1000,400,800,32),(200,800,400,32),(800,800,600,32),
  (1600,600,32,500),(1800,400,700,32),(2200,600,32,400),(600,200,32,500),
  (1200,200,32,300),(400,1000,32,400),(800,1000,32,300),(200,1200,700,32),
  (1100,1000,600,32),(1800,1000,32,600),(2000,1200,500,32),(2400,1000,32,500),
  (200,1600,500,32),(900,1400,32,500),(1100,1600,600,32),(1800,1600,32,400),
  (2000,1600,700,32),(2400,1600,32,400),(200,2000,400,32),(800,2000,600,32),
  (1600,1800,32,400),(2000,2000,500,32),(1200,2200,32,400),(400,2400,600,32),
  (1400,2400,700,32),(2200,2200,32,500),(100,2600,300,32),(500,2600,200,32),
]

def wall_collide(x, y, r):
    for (wx,wy,ww,wh) in WALLS:
        nx = max(wx, min(x, wx+ww))
        ny = max(wy, min(y, wy+wh))
        if math.hypot(x-nx, y-ny) < r:
            return True
    return False

def line_of_sight(x1, y1, x2, y2):
    dx = x2-x1
    dy = y2-y1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return True
    steps = int(dist/20)
    for i in range(1, steps):
        t = i/steps
        cx = x1+dx*t
        cy = y1+dy*t
        for (wx,wy,ww,wh) in WALLS:
            if wx <= cx <= wx+ww and wy <= cy <= wy+wh:
                return False
    return True

def ray_hits_wall(x1, y1, dx, dy, max_dist):
    steps = int(max_dist/16)
    for i in range(1, steps):
        t = i/steps * max_dist
        cx = x1+dx*t
        cy = y1+dy*t
        for (wx,wy,ww,wh) in WALLS:
            if wx <= cx <= wx+ww and wy <= cy <= wy+wh:
                return True
    return False

state = {
    "running": False,
    "players": {},
    "zombies": {},
    "wave": 0,
    "wave_active": False,
    "projectiles": [],
    "between_waves": False,
    "wave_countdown": 0,
    "shop_pos":     {"x":300,  "y":2700},
    "player_spawn": {"x":300,  "y":2800},
    "zombie_spawn": {"x":1500, "y":100},
}

zombie_id_counter = 0
projectile_id_counter = 0
game_thread = None
TICK_RATE = 20
WAVE_DELAY = 15
BANNER_DELAY = 3

def get_wave_config(wave):
    count = min(10+(wave-1)*10, 120)
    scale = max(0, wave-12)
    speed  = min(55+wave*4+scale*6, 220)
    health = 40+wave*15+scale*30
    damage = 8+wave*2+scale*3
    is_boss_wave = False
    if wave % 5 == 0 and wave <= 12:
        is_boss_wave = True
    elif wave > 14 and (wave % 2 == 0):
        is_boss_wave = True
    boss_health = 400+wave*150+scale*200
    boss_proj_cooldown = max(1.5-wave*0.03, 0.35)
    return {
        "count": count, "speed": speed, "health": health,
        "damage": damage, "is_boss_wave": is_boss_wave,
        "boss_health": boss_health, "boss_proj_cooldown": boss_proj_cooldown,
    }

def dist(a, b):
    return math.hypot(a["x"]-b["x"], a["y"]-b["y"])

def nearest_player_los(pos):
    best_los, best_los_d = None, float("inf")
    best_any, best_any_d = None, float("inf")
    for p in state["players"].values():
        if not p.get("alive", True):
            continue
        d = dist(pos, p["pos"])
        if d < best_any_d:
            best_any_d = d
            best_any = p
        if d < best_los_d and line_of_sight(pos["x"], pos["y"], p["pos"]["x"], p["pos"]["y"]):
            best_los_d = d
            best_los = p
    return best_los, best_any

def normalize(dx, dy):
    mag = math.hypot(dx, dy)
    if mag == 0:
        return 0, 0
    return dx/mag, dy/mag

def spawn_wave(wave):
    global zombie_id_counter
    cfg = get_wave_config(wave)
    state["wave_active"] = True
    state["between_waves"] = False

    # Spread zombies across the full top section not just one spot
    spawn_zones = [
        (200, 50, 800, 150),
        (900, 50, 1600, 150),
        (1700, 50, 2400, 150),
        (200, 150, 800, 300),
        (900, 150, 1600, 300),
        (1700, 150, 2400, 300),
    ]

    for i in range(cfg["count"]):
        zombie_id_counter += 1
        zid = f"z{zombie_id_counter}"
        zone = spawn_zones[i % len(spawn_zones)]
        for _ in range(30):
            sx = random.randint(zone[0], zone[2])
            sy = random.randint(zone[1], zone[3])
            sx = max(50, min(2950, sx))
            sy = max(50, min(2950, sy))
            if not wall_collide(sx, sy, 20):
                break
        state["zombies"][zid] = {
            "id": zid, "x": sx, "y": sy,
            "health": cfg["health"], "max_health": cfg["health"],
            "speed": cfg["speed"], "damage": cfg["damage"],
            "type": "normal", "last_attack": 0,
            "wander_angle": random.uniform(0, math.pi*2),
            "wander_timer": 0, "can_see_player": False,
        }

    if cfg["is_boss_wave"]:
        zombie_id_counter += 1
        bid = f"z{zombie_id_counter}"
        state["zombies"][bid] = {
            "id": bid,
            "x": state["zombie_spawn"]["x"],
            "y": state["zombie_spawn"]["y"],
            "health": cfg["boss_health"], "max_health": cfg["boss_health"],
            "speed": max(cfg["speed"]*0.4, 25),
            "damage": cfg["damage"]*2,
            "type": "boss", "last_attack": 0,
            "last_shot": 0, "proj_cooldown": cfg["boss_proj_cooldown"],
            "wander_angle": 0, "wander_timer": 0, "can_see_player": False,
        }

    socketio.emit("wave_start", {"wave": wave, "boss": cfg["is_boss_wave"]})

def start_wave_countdown():
    state["between_waves"] = True
    state["wave_countdown"] = 0

    def tick():
        # Wait for wave clear banner to finish before showing countdown
        time.sleep(BANNER_DELAY)
        if not state["running"] or not state["between_waves"]:
            return
        remaining = WAVE_DELAY
        state["wave_countdown"] = remaining
        socketio.emit("wave_countdown", {"seconds": remaining})
        while remaining > 0 and state["running"] and state["between_waves"]:
            time.sleep(1)
            remaining -= 1
            state["wave_countdown"] = remaining
            socketio.emit("wave_countdown", {"seconds": remaining})
        if state["running"] and state["between_waves"]:
            state["wave"] += 1
            spawn_wave(state["wave"])

    threading.Thread(target=tick, daemon=True).start()

def game_loop():
    global projectile_id_counter
    last_time = time.time()

    while state["running"]:
        now = time.time()
        dt = now-last_time
        last_time = now

        if not state["players"]:
            time.sleep(1/TICK_RATE)
            continue

        if not state["wave_active"] and not state["zombies"] and not state["between_waves"]:
            start_wave_countdown()

        new_projectiles = []
        zombie_list = list(state["zombies"].values())

        for zid, z in list(state["zombies"].items()):
            pos = {"x": z["x"], "y": z["y"]}
            los_target, any_target = nearest_player_los(pos)

            if los_target:
                z["can_see_player"] = True
                tx = los_target["pos"]["x"]
                ty = los_target["pos"]["y"]
                dx = tx-z["x"]
                dy = ty-z["y"]
                d = math.hypot(dx, dy)
                ndx, ndy = normalize(dx, dy)
            else:
                z["can_see_player"] = False
                z["wander_timer"] -= dt
                if z["wander_timer"] <= 0:
                    if any_target and random.random() < 0.4:
                        dx = any_target["pos"]["x"]-z["x"]
                        dy = any_target["pos"]["y"]-z["y"]
                        z["wander_angle"] = math.atan2(dy,dx)+random.uniform(-0.8,0.8)
                    else:
                        z["wander_angle"] += random.uniform(-1.0,1.0)
                    z["wander_timer"] = random.uniform(0.5,2.0)
                ndx = math.cos(z["wander_angle"])
                ndy = math.sin(z["wander_angle"])
                d = 9999

            # Separation — push away from nearby zombies
            sep_x, sep_y = 0, 0
            sep_r = 36 if z["type"] == "boss" else 24
            for other in zombie_list:
                if other["id"] == zid:
                    continue
                odx = z["x"]-other["x"]
                ody = z["y"]-other["y"]
                od = math.hypot(odx, ody)
                if od < sep_r and od > 0:
                    sep_x += (odx/od) * (sep_r-od) * 0.3
                    sep_y += (ody/od) * (sep_r-od) * 0.3

            step = z["speed"]*dt
            r = 28 if z["type"] == "boss" else 16
            nx = z["x"] + ndx*step + sep_x*dt*60
            ny = z["y"] + ndy*step + sep_y*dt*60

            if not wall_collide(nx, ny, r):
                z["x"], z["y"] = nx, ny
            elif not wall_collide(nx, z["y"], r):
                z["x"] = nx
                if not z["can_see_player"]:
                    z["wander_angle"] += random.uniform(-1.5,1.5)
            elif not wall_collide(z["x"], ny, r):
                z["y"] = ny
                if not z["can_see_player"]:
                    z["wander_angle"] += random.uniform(-1.5,1.5)
            else:
                z["wander_angle"] = random.uniform(0, math.pi*2)
                z["wander_timer"] = 0

            z["x"] = max(r, min(2968-r, z["x"]))
            z["y"] = max(r, min(2968-r, z["y"]))

            if z["type"] == "normal" and d < 32 and los_target:
                if now-z["last_attack"] > 1.0:
                    z["last_attack"] = now
                    pid = los_target["id"]
                    state["players"][pid]["health"] = max(0, state["players"][pid]["health"]-z["damage"])
                    if state["players"][pid]["health"] <= 0:
                        state["players"][pid]["health"] = 100
                        state["players"][pid]["pos"] = dict(state["player_spawn"])
                        socketio.emit("player_died", {"id": pid})

            if z["type"] == "boss" and los_target:
                if d < 50:
                    if now-z["last_attack"] > 1.5:
                        z["last_attack"] = now
                        pid = los_target["id"]
                        state["players"][pid]["health"] = max(0, state["players"][pid]["health"]-z["damage"])
                        if state["players"][pid]["health"] <= 0:
                            state["players"][pid]["health"] = 100
                            state["players"][pid]["pos"] = dict(state["player_spawn"])
                            socketio.emit("player_died", {"id": pid})
                if now-z.get("last_shot",0) > z["proj_cooldown"]:
                    z["last_shot"] = now
                    snap_x = los_target["pos"]["x"]
                    snap_y = los_target["pos"]["y"]
                    pdx, pdy = normalize(snap_x-z["x"], snap_y-z["y"])
                    projectile_id_counter += 1
                    new_projectiles.append({
                        "id": f"p{projectile_id_counter}",
                        "x": z["x"], "y": z["y"],
                        "dx": pdx, "dy": pdy,
                        "speed": 280, "owner": zid,
                    })

        live = []
        for p in state["projectiles"]+new_projectiles:
            p["x"] += p["dx"]*p["speed"]*dt
            p["y"] += p["dy"]*p["speed"]*dt
            hit = False
            for player in state["players"].values():
                if dist({"x":p["x"],"y":p["y"]}, player["pos"]) < 20:
                    player["health"] = max(0, player["health"]-25)
                    if player["health"] <= 0:
                        player["health"] = 100
                        player["pos"] = dict(state["player_spawn"])
                        socketio.emit("player_died", {"id": player["id"]})
                    hit = True
                    break
            if wall_collide(p["x"], p["y"], 4): hit = True
            if p["x"]<0 or p["x"]>3000 or p["y"]<0 or p["y"]>3000: hit = True
            if not hit:
                live.append(p)
        state["projectiles"] = live

        if state["wave_active"] and not state["zombies"]:
            state["wave_active"] = False
            socketio.emit("wave_clear", {"wave": state["wave"]})

        socketio.emit("game_state", {
            "players": state["players"],
            "zombies": {zid: {
                "id":z["id"],"x":z["x"],"y":z["y"],
                "health":z["health"],"max_health":z["max_health"],
                "type":z["type"],"can_see_player":z.get("can_see_player",False)
            } for zid,z in state["zombies"].items()},
            "projectiles": state["projectiles"],
            "wave": state["wave"],
            "countdown": state["wave_countdown"] if state["between_waves"] else 0,
        })

        time.sleep(1/TICK_RATE)

def reset_game():
    global zombie_id_counter, projectile_id_counter
    state["running"] = False
    state["players"] = {}
    state["zombies"] = {}
    state["projectiles"] = []
    state["wave"] = 0
    state["wave_active"] = False
    state["between_waves"] = False
    state["wave_countdown"] = 0
    zombie_id_counter = 0
    projectile_id_counter = 0

def start_shutdown_timer():
    def shutdown():
        time.sleep(5)
        if not state["players"]:
            reset_game()
            socketio.emit("server_idle", {})
    threading.Thread(target=shutdown, daemon=True).start()

def start_game():
    global game_thread
    state["running"] = True
    game_thread = threading.Thread(target=game_loop, daemon=True)
    game_thread.start()

@socketio.on("connect")
def on_connect():
    pid = request.sid
    was_empty = len(state["players"]) == 0
    state["players"][pid] = {
        "id": pid, "pos": dict(state["player_spawn"]),
        "health": 100, "alive": True, "money": 0,
        "gun": "pistol", "guns": ["pistol"], "angle": 0, "name": "Player",
    }
    emit("your_id", {"id": pid, "spawn": state["player_spawn"], "shop": state["shop_pos"]})
    if was_empty and not state["running"]:
        start_game()
    socketio.emit("player_joined", {"id": pid, "players": state["players"]})

@socketio.on("disconnect")
def on_disconnect():
    pid = request.sid
    if pid in state["players"]:
        del state["players"][pid]
    socketio.emit("player_left", {"id": pid})
    if not state["players"]:
        start_shutdown_timer()

@socketio.on("player_update")
def on_player_update(data):
    pid = request.sid
    if pid in state["players"]:
        state["players"][pid]["pos"]   = data["pos"]
        state["players"][pid]["angle"] = data.get("angle", 0)
        state["players"][pid]["gun"]   = data.get("gun", "pistol")

@socketio.on("shoot")
def on_shoot(data):
    pid = request.sid
    if pid not in state["players"]: return
    zid = data.get("zid")
    damage = data.get("damage", 0)
    if zid and zid in state["zombies"]:
        state["zombies"][zid]["health"] -= damage
        if state["zombies"][zid]["health"] <= 0:
            ztype = state["zombies"][zid]["type"]
            del state["zombies"][zid]
            reward = 150 if ztype == "boss" else 15
            state["players"][pid]["money"] += reward
            emit("kill_reward", {"money": state["players"][pid]["money"]})

@socketio.on("buy_gun")
def on_buy_gun(data):
    pid = request.sid
    gun = data.get("gun")
    prices = {"shotgun":500,"smg":750,"ar":1000,"sniper":1500,"minigun":2500,"rocket":3500}
    if gun in prices:
        cost = prices[gun]
        player = state["players"].get(pid)
        if player and player["money"] >= cost and gun not in player["guns"]:
            player["money"] -= cost
            player["guns"].append(gun)
            player["gun"] = gun
            emit("buy_success", {"gun":gun,"money":player["money"],"guns":player["guns"]})

@socketio.on("set_name")
def on_set_name(data):
    pid = request.sid
    if pid in state["players"]:
        state["players"][pid]["name"] = data.get("name","Player")[:16]

@app.route("/")
def index():
    with open("index.html","r") as f:
        return f.read()

if __name__ == "__main__":
    print("🧟 Zombie server starting on port 5000...")
    socketio.run(app, host="0.0.0.0", port=5000)