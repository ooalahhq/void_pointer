import math
import random
import sys
import time
import argparse
from pathlib import Path
import pygame
import pygame.freetype
from title_intro import TitleIntro, INTRO_DURATION
from combat_fx import CombatFX

pygame.init()
W, H = 1280, 800
SCREEN = pygame.display.set_mode((W, H))
WORLD_FRAME = pygame.Surface((W-72,H-145))
pygame.display.set_caption('Void Pointer: Last Light — Pixel Art + SFX')
CLOCK = pygame.time.Clock()
FONT = pygame.freetype.SysFont('consolas', 22)
SMALL = pygame.freetype.SysFont('consolas', 15)
BIG = pygame.freetype.SysFont('consolas', 50, bold=True)
BG=(10,15,29); WHITE=(214,231,241); CYAN=(94,235,255); VIOLET=(166,145,251)
GOLD=(232,190,92); RED=(235,107,128); DIM=(35,49,68)
HEAL_GREEN=(112,245,170)
MAX_HP=3
SKILL_COOLDOWNS={'dash':4,'shield':10,'pulse':12}
SKILL_KEYS={pygame.K_e:(0,'dash'),pygame.K_q:(0,'shield'),pygame.K_f:(0,'pulse'),
            pygame.K_RCTRL:(1,'dash'),pygame.K_RSHIFT:(1,'shield'),pygame.K_RETURN:(1,'pulse')}
ARENA=pygame.Rect(36,105,W-72,H-145)
BOSS_START_POS=pygame.Vector2(W//2,180)
BOSS_BOUNDS=ARENA.inflate(-100,-140)
RNG=random.Random()
ASSETS=Path(__file__).resolve().parent/'assets'
# Isi dengan absolute path file backsound, misalnya '/home/ucup/Music/backsound.ogg'.
BACKSOUND_PATH = '/home/ucup/FREELANCE/void_pointer/assets/backsound/boss.mp3'
BACKSOUND_VOLUME = 0.4
SPRITES={}
for i in range(3):
    source=pygame.image.load(str(ASSETS/'sprites'/f'warden_{i}.png')).convert_alpha()
    SPRITES[i]=pygame.transform.scale(source,(64,96))
SWORD_SPRITE=pygame.transform.scale(pygame.image.load(str(ASSETS/'sprites'/'sword.png')).convert_alpha(),(30,30))
SOUNDS={}
try:
    if not pygame.mixer.get_init(): pygame.mixer.init()
    for name in ('pickup','sword_spawn','strike','orb','hurt','warning','laser','phase','win'):
        SOUNDS[name]=pygame.mixer.Sound(str(ASSETS/'sfx'/f'{name}.wav'))
except (pygame.error,OSError) as exc:
    print('Audio disabled:',exc)

if BACKSOUND_PATH:
    try:
        if not pygame.mixer.get_init(): pygame.mixer.init()
        pygame.mixer.music.load(BACKSOUND_PATH)
        pygame.mixer.music.set_volume(BACKSOUND_VOLUME)
        pygame.mixer.music.play(-1)
    except (pygame.error,OSError) as exc:
        print('Backsound disabled:',exc)

def sfx(name):
    sound=SOUNDS.get(name)
    if sound: sound.play()


def text(s, x, y, color=WHITE, font=FONT, center=False):
    surf,_=font.render(s, color)
    SCREEN.blit(surf, surf.get_rect(center=(x,y)) if center else (x,y))

class Player:
    def __init__(self, pos, color, keys, name):
        self.pos=pygame.Vector2(pos); self.color=color; self.keys=keys; self.name=name
        self.hp=MAX_HP; self.sword=False; self.invuln=0; self.alive=True
        self.facing=pygame.Vector2(0,-1)
        self.dash_direction=pygame.Vector2(0,-1)
        self.dash_time=0;self.shield_time=0
        self.block_feedback=0
        self.cooldowns={skill:0 for skill in SKILL_COOLDOWNS}
    def update(self, dt, held, pointer=None, hand_mode=False):
        if not self.alive: return
        move=pygame.Vector2()
        if pointer is not None:
            move=pygame.Vector2(pointer)-self.pos
            if move.length_squared()<9:move=pygame.Vector2()
        elif not hand_mode:
            dx=int(held[self.keys[3]])-int(held[self.keys[2]])
            dy=int(held[self.keys[1]])-int(held[self.keys[0]])
            move=pygame.Vector2(dx,dy)
        if move.length_squared():self.facing=move.normalize()
        dash_dt=min(dt,self.dash_time)
        self.pos+=self.dash_direction*850*dash_dt
        if move.length_squared():
            distance=260*(dt-dash_dt)
            if pointer is not None:distance=min(distance,move.length())
            self.pos+=self.facing*distance
        self.dash_time=max(0,self.dash_time-dt)
        self.shield_time=max(0,self.shield_time-dt)
        self.block_feedback=max(0,self.block_feedback-dt)
        for skill in self.cooldowns:self.cooldowns[skill]=max(0,self.cooldowns[skill]-dt)
        self.pos.x=max(ARENA.left+8,min(ARENA.right-8,self.pos.x))
        self.pos.y=max(ARENA.top+8,min(ARENA.bottom-8,self.pos.y))
        self.invuln=max(0,self.invuln-dt)
    def hit(self, final):
        if not self.alive or self.invuln>0 or self.shield_time>0: return
        sfx('hurt')
        self.hp=0 if final else self.hp-1
        self.alive=self.hp>0
        if not self.alive: self.sword=False
        self.invuln=1.05
    def draw(self):
        if not self.alive: return
        if self.shield_time>0:
            pygame.draw.circle(SCREEN,CYAN,self.pos,24,3)
            pygame.draw.circle(SCREEN,WHITE,self.pos,28,1)
        if self.dash_time>0:
            pygame.draw.line(SCREEN,self.color,self.pos-self.dash_direction*40,self.pos,5)
        if self.invuln>0 and int(self.invuln*12)%2==0: return
        x,y=map(int,self.pos)
        pygame.draw.polygon(SCREEN,self.color,[(x,y-8),(x+8,y),(x,y+8),(x-8,y)])
        pygame.draw.circle(SCREEN,BG,(x,y),2)
        if self.sword:
            pygame.draw.circle(SCREEN,GOLD,(x,y),16,2)
            pygame.draw.line(SCREEN,GOLD,(x+9,y-12),(x+20,y-23),3)

class Orb:
    def __init__(self,pos,velocity):
        self.pos=pygame.Vector2(pos);self.vel=pygame.Vector2(velocity);self.r=7;self.trail=[]
    def update(self,dt):
        self.trail.append(self.pos.copy());self.trail=self.trail[-6:]
        self.pos+=self.vel*dt
    def draw(self):
        for i,pos in enumerate(self.trail):
            pygame.draw.circle(SCREEN,(55+i*15,25+i*5,38+i*6),pos,max(1,i//2+1))
        pygame.draw.circle(SCREEN,(65,29,42),self.pos,self.r+4)
        pygame.draw.circle(SCREEN,RED,self.pos,self.r)
        pygame.draw.circle(SCREEN,(255,194,195),self.pos,2)

class HealingOrb:
    def __init__(self, pos, now):
        self.pos=pygame.Vector2(pos)
        self.expires=now+8
    def draw(self, now):
        if self.expires-now<2 and int(now*8)%2==0:return
        pulse=math.sin(now*5)
        pygame.draw.circle(SCREEN,(28,65,48),self.pos,int(19+2*pulse))
        pygame.draw.circle(SCREEN,HEAL_GREEN,self.pos,12,2)
        x,y=self.pos
        pygame.draw.line(SCREEN,HEAL_GREEN,(x-5,y),(x+5,y),3)
        pygame.draw.line(SCREEN,HEAL_GREEN,(x,y-5),(x,y+5),3)

class HealPulse:
    def __init__(self, pos):
        self.pos=pygame.Vector2(pos)
        self.life=.7
    def update(self, dt):self.life=max(0,self.life-dt)
    def draw(self):
        progress=1-self.life/.7
        pygame.draw.circle(SCREEN,HEAL_GREEN,self.pos,int(14+progress*22),1)
        text('+1 HP',self.pos.x,self.pos.y-25-progress*22,HEAL_GREEN,SMALL,True)

class PulseEffect:
    def __init__(self, pos, color):
        self.pos=pygame.Vector2(pos);self.color=color;self.life=.4
    def update(self, dt):self.life=max(0,self.life-dt)
    def draw(self):
        radius=int(12+138*(1-self.life/.4))
        pygame.draw.circle(SCREEN,self.color,self.pos,radius,3)
        pygame.draw.circle(SCREEN,WHITE,self.pos,max(1,radius-6),1)

def activate_skill(state, player, action):
    # Input-independent entry point: keyboard now, gesture recognition later.
    if (action not in SKILL_COOLDOWNS or state['phase'] not in ('boss','duel')
            or not player.alive or player.cooldowns[action]>0):return False
    player.cooldowns[action]=SKILL_COOLDOWNS[action]
    if action=='dash':
        player.dash_direction=player.facing.copy()
        player.dash_time=.16
        player.invuln=max(player.invuln,.24)
        state['fx'].burst(player.pos,player.color,16,140,30)
    elif action=='shield':
        player.shield_time=1.2
        state['fx'].burst(player.pos,CYAN,24,100,40)
    elif action=='pulse':
        for orb in state['orbs']:
            if orb.pos.distance_to(player.pos)<=150:
                state['fx'].burst(orb.pos,RED,10,150,25)
        state['orbs']=[orb for orb in state['orbs'] if orb.pos.distance_to(player.pos)>150]
        state['effects'].append(PulseEffect(player.pos,player.color))
        state['fx'].burst(player.pos,player.color,60,300,150)
        state['fx'].shake(8,.3)
    sfx('phase')
    return True

def draw_skill_hud(player, x, labels):
    for index,(action,label) in enumerate(zip(SKILL_COOLDOWNS,labels)):
        cooldown=player.cooldowns[action]
        status='READY' if cooldown<=0 else str(math.ceil(cooldown))+'s'
        color=player.color if player.alive and cooldown<=0 else DIM
        text(label+' '+action.upper()+' '+status,x+index*150,82,color,SMALL)

def healing_spawn(state):
    for _ in range(100):
        pos=pygame.Vector2(RNG.uniform(ARENA.left+28,ARENA.right-28),
                           RNG.uniform(ARENA.top+28,ARENA.bottom-28))
        if pos.distance_to(state['boss_pos'])<90:continue
        if any(p.alive and pos.distance_to(p.pos)<60 for p in state['players']):continue
        if state['sword'] is not None and pos.distance_to(state['sword'])<40:continue
        if any(pos.distance_to(orb.pos)<50 for orb in state['orbs']):continue
        if any(laser.rect().inflate(40,40).collidepoint(pos) for laser in state['lasers']):continue
        return pos
    return None

def update_healing(state, now):
    if state['phase']!='boss' or state['boss_hp']<=0 or not any(p.alive for p in state['players']):
        state['healing']=None
        return
    orb=state['healing']
    if orb is not None and now>=orb.expires:
        state['healing']=None
        orb=None
    if orb is None and now>=state['next_healing']:
        pos=healing_spawn(state)
        if pos is None:
            state['next_healing']=now+1
            return
        orb=HealingOrb(pos,now)
        state['healing']=orb
        state['next_healing']=now+RNG.uniform(10,16)
    if orb is not None:
        eligible=[p for p in state['players'] if p.alive and p.hp<MAX_HP
                  and p.pos.distance_to(orb.pos)<20]
        if eligible:
            distance=min(p.pos.distance_to(orb.pos) for p in eligible)
            player=RNG.choice([p for p in eligible if p.pos.distance_to(orb.pos)<=distance+.001])
            player.hp=min(MAX_HP,player.hp+1)
            state['healing']=None
            state['effects'].append(HealPulse(player.pos))
            state['fx'].burst(player.pos,HEAL_GREEN,32,160,55)
            sfx('pickup')

class Laser:
    def __init__(self, horizontal, coordinate, now, warning=.85, duration=.75):
        self.horizontal=horizontal;self.coordinate=coordinate
        self.start=now; self.warning=warning;self.duration=duration
    def active(self,now): return self.start+self.warning<=now<self.start+self.warning+self.duration
    def expired(self,now): return now>=self.start+self.warning+self.duration
    def rect(self):
        if self.horizontal:return pygame.Rect(ARENA.left,self.coordinate-12,ARENA.width,24)
        return pygame.Rect(self.coordinate-12,ARENA.top,24,ARENA.height)
    def draw(self,now):
        active=self.active(now)
        color=(255,208,218) if active else (115,54,72)
        width=24 if active else 2
        if self.horizontal: pygame.draw.line(SCREEN,color,(ARENA.left,self.coordinate),(ARENA.right,self.coordinate),width)
        else: pygame.draw.line(SCREEN,color,(self.coordinate,ARENA.top),(self.coordinate,ARENA.bottom),width)

class Slash:
    def __init__(self, origin, target):
        self.pos=pygame.Vector2(origin)
        direction=target-self.pos
        self.angle=direction.as_polar()[1] if direction.length_squared() else -90
        self.life=.32
        self.sparks=[(pygame.Vector2(target),pygame.Vector2(1,0).rotate(i*30)*RNG.uniform(90,180))
                     for i in range(12)]
    def update(self, dt):
        self.life=max(0,self.life-dt)
        for pos,vel in self.sparks: pos+=vel*dt
    def draw(self):
        progress=1-self.life/.32
        tip=self.pos+pygame.Vector2(48,0).rotate(self.angle-65+130*progress)
        trail=self.pos+pygame.Vector2(42,0).rotate(self.angle-90+130*progress)
        pygame.draw.polygon(SCREEN,GOLD,[self.pos,trail,tip])
        pygame.draw.line(SCREEN,WHITE,self.pos,tip,3)
        for pos,_ in self.sparks:
            pygame.draw.circle(SCREEN,GOLD,pos,max(1,int(4*(1-progress))))

def boss_stage(hp):
    return 1 if hp>5 else (2 if hp>2 else 3)

BOSS_STAGE_NAMES={1:'HUNT',2:'BARRAGE',3:'LAST LIGHT'}

def boss_destination(pos):
    for _ in range(100):
        target=pygame.Vector2(RNG.uniform(BOSS_BOUNDS.left,BOSS_BOUNDS.right),
                              RNG.uniform(BOSS_BOUNDS.top,BOSS_BOUNDS.bottom))
        if target.distance_to(pos)>100:return target
    return pygame.Vector2(BOSS_BOUNDS.center)

def update_boss_movement(state, now, dt):
    if state['phase']!='boss' or state['boss_hp']<=0:return
    pos=state['boss_pos']
    if now>=state['next_speed_change']:
        state['boss_fast']=not state['boss_fast']
        if state['boss_fast']:
            state['boss_speed']=RNG.uniform(290,380)
            state['next_speed_change']=now+RNG.uniform(.45,.95)
        else:
            state['boss_speed']=RNG.uniform(65,110)
            state['next_speed_change']=now+RNG.uniform(1,2.2)
        state['boss_target']=boss_destination(pos)
    direction=state['boss_target']-pos
    distance=direction.length()
    if distance:
        pos+=direction/distance*min(distance,state['boss_speed']*dt)
    pos.x=max(BOSS_BOUNDS.left,min(BOSS_BOUNDS.right,pos.x))
    pos.y=max(BOSS_BOUNDS.top,min(BOSS_BOUNDS.bottom,pos.y))
    if pos.distance_to(state['boss_target'])<1:
        state['boss_target']=boss_destination(pos)

def update_boss_attacks(state, now):
    living=[p for p in state['players'] if p.alive]
    if not living or state['boss_hp']<=0: return
    stage=boss_stage(state['boss_hp'])
    if stage!=state['boss_stage']:
        state['boss_stage']=stage
        state['orbs'].clear();state['lasers'].clear()
        state['ring_at']=None
        state['next_orb']=now+1.2;state['next_laser']=now+2
        state['stage_notice']=1.2;state['transition']=.65
        state['attack_count']=0
        state['fx'].burst(state['boss_pos'],VIOLET,64,280,150)
        state['fx'].shake(7,.35)
        sfx('phase')
    if state['ring_at'] is not None and now>=state['ring_at']:
        origin=state['boss_pos']+pygame.Vector2(0,40)
        for angle in range(0,360,30):
            state['orbs'].append(Orb(origin,pygame.Vector2(155,0).rotate(angle+15)))
        state['ring_at']=None
        state['fx'].burst(origin,RED,40,240,95)
        state['fx'].shake(5,.2)
        sfx('orb')
    if now>=state['next_orb']:
        state['next_orb']=now+{1:.8,2:1.1,3:1.35}[stage]
        state['attack_count']+=1
        if stage==3 and state['attack_count']%2==0:
            state['ring_at']=now+.8
            sfx('warning')
        else:
            origin=state['boss_pos']+pygame.Vector2(0,40)
            direction=RNG.choice(living).pos-origin
            if not direction.length_squared(): direction=pygame.Vector2(0,1)
            direction=direction.normalize()
            angles={1:(0,),2:(-22,0,22),3:(-36,-18,0,18,36)}[stage]
            for angle in angles:
                state['orbs'].append(Orb(origin,direction.rotate(angle)*{1:150,2:165,3:175}[stage]))
            sfx('orb')
    if stage>=2 and now>=state['next_laser']:
        state['next_laser']=now+(4 if stage==2 else 3)
        target=RNG.choice(living)
        horizontal=RNG.choice([True,False])
        coordinate=target.pos.y if horizontal else target.pos.x
        state['lasers'].append(Laser(horizontal,coordinate,now,warning=1.1,duration=.45))
        sfx('warning')

def update_lasers(state, now, dt, final):
    for laser in state['lasers'][:]:
        if laser.active(now):
            if now-dt<laser.start+laser.warning:
                sfx('laser');state['fx'].shake(4,.18)
            area=laser.rect()
            for p in state['players']:
                if p.alive and area.colliderect(pygame.Rect(p.pos.x-6,p.pos.y-6,12,12)):
                    damage_player(state,p,final)
        if laser.expired(now):state['lasers'].remove(laser)

def damage_player(state, player, final):
    previous_hp=player.hp
    player.hit(final)
    if player.hp<previous_hp:
        state['fx'].burst(player.pos,RED,28 if player.alive else 65,220,65)
        state['fx'].shake(5 if player.alive else 10,.3)
    elif player.alive and player.shield_time>0 and player.block_feedback<=0:
        state['fx'].burst(player.pos,CYAN,12,120,35)
        player.block_feedback=.2

def new_game(intro=False):
    return dict(phase='intro' if intro else 'boss',intro_time=0,
                players=[Player((W*.22,H-140),CYAN,(pygame.K_w,pygame.K_s,pygame.K_a,pygame.K_d),'P1'),
                     Player((W*.78,H-140),VIOLET,(pygame.K_UP,pygame.K_DOWN,pygame.K_LEFT,pygame.K_RIGHT),'P2')],
                boss_hp=8, sword=pygame.Vector2(W*.47,H*.6),orbs=[],lasers=[],next_orb=1.2,
                next_laser=0, elapsed=0, message='',winner=None,hit_by=[0,0],boss_hurt=0,transition=0,
                boss_stage=1,stage_notice=0,ring_at=None,attack_count=0,effects=[],
                boss_pos=pygame.Vector2(BOSS_START_POS),boss_target=boss_destination(BOSS_START_POS),
                boss_speed=85,boss_fast=False,next_speed_change=RNG.uniform(1,2),
                healing=None,next_healing=RNG.uniform(8,12),fx=CombatFX((W,H)))

def update_intro(state, dt, skip=False):
    if state['phase']!='intro':return
    state['intro_time']+=dt
    if skip or state['intro_time']>=INTRO_DURATION:
        state['phase']='boss'
        state['elapsed']=0
        state['transition']=.85
        sfx('phase')

def sword_spawn(players, boss_pos):
    # Generate inside arena, outside boss and away from players.
    for _ in range(100):
        p=pygame.Vector2(RNG.randint(ARENA.left+35,ARENA.right-35),RNG.randint(ARENA.top+110,ARENA.bottom-30))
        if all(p.distance_to(pl.pos)>60 for pl in players if pl.alive) and p.distance_to(boss_pos)>75:return p
    return pygame.Vector2(W/2,H/2)

def ensure_sword(state):
    players=state['players']
    if (state['boss_hp']>0 and state['sword'] is None
            and any(p.alive for p in players)
            and not any(p.alive and p.sword for p in players)):
        state['sword']=sword_spawn(players,state['boss_pos'])
        state['fx'].burst(state['sword'],GOLD,20,100,35)
        sfx('sword_spawn')

def boss_sprite(pos, now, hurt=0):
    bob=math.sin(now*2.5)*3
    frame=2 if hurt>0 else (int(now*2)%2)
    sprite=SPRITES[frame]
    r=sprite.get_rect(center=(int(pos.x),int(pos.y+bob+12)))
    SCREEN.blit(sprite,r)
    if hurt>0:
        overlay=pygame.Surface(sprite.get_size(),pygame.SRCALPHA)
        overlay.fill((244,190,208,110))
        SCREEN.blit(overlay,r)

def draw_combat_fx(state):
    # Move only the arena image: HUD and collision coordinates stay stable.
    old_clip=SCREEN.get_clip()
    SCREEN.set_clip(ARENA)
    state['fx'].draw(SCREEN)
    offset=state['fx'].offset()
    if offset!=(0,0):
        WORLD_FRAME.blit(SCREEN,(0,0),ARENA)
        SCREEN.fill(BG,ARENA)
        SCREEN.blit(WORLD_FRAME,(ARENA.left+offset[0],ARENA.top+offset[1]))
    SCREEN.set_clip(old_clip)


def draw_hand_status(controls):
    if controls is None:return
    status,_=controls.tracker.status
    fps=getattr(controls.tracker,'inference_fps',0)
    text('HAND: '+status[:51]+'  '+str(round(fps))+' FPS',36,H-27,HEAL_GREEN if any(controls.tracked) else GOLD,SMALL)
    for slot,x in enumerate((36,W-260)):
        label=('HOLD' if controls.held[slot] else ('TRACKED' if controls.gates[slot].armed else 'POINT TO ARM')) if controls.tracked[slot] else 'SHOW HAND'
        text('P'+str(slot+1)+' '+label,x,22,CYAN if slot==0 else VIOLET,SMALL)
    text('H keys  C calibrate  K rebind  T camera',W-390,H-27,WHITE,SMALL)
    frame=controls.last_frame
    if frame and frame.preview and getattr(controls.tracker,'preview_enabled',False):
        rect=pygame.Rect(ARENA.right-252,ARENA.top+10,*frame.preview_size)
        preview=pygame.image.frombuffer(frame.preview,frame.preview_size,'RGB')
        SCREEN.blit(preview,rect)
        old_clip=SCREEN.get_clip();SCREEN.set_clip(rect)
        for hand in frame.hands:
            color=CYAN if hand.sample is controls.raw[0] else VIOLET if hand.sample is controls.raw[1] else RED
            points=hand.sample.landmarks
            if points:
                from hand_control.tracker import HAND_CONNECTIONS
                mapped=[(rect.left+p[0]*rect.width,rect.top+p[1]*rect.height) for p in points]
                for a,b in HAND_CONNECTIONS:pygame.draw.line(SCREEN,color,mapped[a],mapped[b],1)
                pygame.draw.circle(SCREEN,WHITE,mapped[8],4)
        SCREEN.set_clip(old_clip)
        pygame.draw.rect(SCREEN,DIM,rect,2)
        caption='CAMERA: '+str(len(frame.hands))+' HANDS / T HIDE'
        if time.monotonic()-frame.t>controls.camera.stale_after:caption='CAMERA: STALE / T HIDE'
        text(caption,rect.left,rect.bottom+5,WHITE,SMALL)
    if controls.calibrating:
        veil=pygame.Surface((W,H),pygame.SRCALPHA)
        veil.fill((7,11,24,170));SCREEN.blit(veil,(0,0))
        text('HAND CALIBRATION',W/2,H/2-55,WHITE,BIG,True)
        text(controls.calibration_prompt(),W/2,H/2,GOLD,SMALL,True)
        text('Point with index finger. Release pinch between corners.',W/2,H/2+35,WHITE,SMALL,True)
        preview=pygame.Rect(W/2-250,H/2+75,500,145)
        pygame.draw.rect(SCREEN,DIM,preview,2)
        pygame.draw.line(SCREEN,DIM,preview.midtop,preview.midbottom,2)
        text('P1 / MIRRORED LEFT',preview.left+12,preview.top+12,CYAN,SMALL)
        text('P2 / MIRRORED RIGHT',preview.centerx+12,preview.top+12,VIOLET,SMALL)
        for slot,sample in enumerate(controls.raw):
            if sample:
                color=CYAN if slot==0 else VIOLET
                pygame.draw.circle(SCREEN,color,(preview.left+sample.x*preview.width,
                                                preview.top+sample.y*preview.height),6)

def reset_and_run(controls=None):
    state=new_game(intro=True)
    intro=TitleIntro((W,H))
    while True:
        dt=min(CLOCK.tick(60)/1000,.05)
        if state['phase']!='intro' and not (controls and controls.calibrating):state['elapsed']+=dt
        now=state['elapsed']
        state['boss_hurt']=max(0,state['boss_hurt']-dt)
        state['transition']=max(0,state['transition']-dt)
        state['stage_notice']=max(0,state['stage_notice']-dt)
        state['fx'].update(dt)
        for effect in state['effects']:effect.update(dt)
        state['effects']=[effect for effect in state['effects'] if effect.life>0]
        for event in pygame.event.get():
            if event.type==pygame.QUIT: pygame.quit();sys.exit()
            if event.type==pygame.KEYDOWN:
                if event.key==pygame.K_ESCAPE:pygame.quit();sys.exit()
                if event.key==pygame.K_r:
                    state=new_game();now=0
                    if controls:controls.reset()
                if controls and event.key==pygame.K_h:
                    controls.tracker.paused=not controls.tracker.paused
                    controls.reset()
                if controls and event.key==pygame.K_k:controls.reset(rebind=True)
                if controls and event.key==pygame.K_t:
                    controls.tracker.preview_enabled=not getattr(controls.tracker,'preview_enabled',False)
                if (controls and not controls.tracker.paused and state['phase'] in ('boss','duel')
                        and event.key==pygame.K_c):
                    if controls.calibrating:controls.reset()
                    else:controls.start_calibration()
                if event.key in (pygame.K_SPACE,pygame.K_RETURN) and state['phase']=='intro':
                    update_intro(state,0,skip=True);now=0
                elif event.key in SKILL_KEYS:
                    index,action=SKILL_KEYS[event.key]
                    if not controls or (controls.tracker.paused and not controls.calibrating):
                        activate_skill(state,state['players'][index],action)
        hand_frame=None
        hand_mode=bool(controls and not controls.tracker.paused)
        if controls and hand_mode:
            hand_frame=controls.poll(time.monotonic(),active=state['phase'] in ('boss','duel'))
            for index,action in hand_frame.actions:
                activate_skill(state,state['players'][index],action)
        if state['phase']=='intro':
            update_intro(state,dt)
            intro.draw(SCREEN,state['intro_time'])
            pygame.display.flip()
            continue
        keys=pygame.key.get_pressed()
        ps=state['players'];phase=state['phase']
        if controls and controls.calibrating:phase='calibration'
        if phase in ('boss','duel'):
            for index,p in enumerate(ps):
                if p.alive and p.dash_time>0:state['fx'].trail(p.pos,p.color,10)
                pointer=hand_frame.targets[index] if hand_frame else None
                p.update(dt,keys,pointer,hand_mode)
        if phase=='boss':
            update_boss_movement(state,now,dt)
            update_boss_attacks(state,now)
            for orb in state['orbs'][:]:
                orb.update(dt)
                if not ARENA.inflate(50,50).collidepoint(orb.pos):state['orbs'].remove(orb);continue
                for p in ps:
                    if p.alive and orb.pos.distance_to(p.pos)<orb.r+7:
                        damage_player(state,p,False)
                        state['fx'].burst(orb.pos,RED,8,100,20)
                        state['orbs'].remove(orb);break
            update_lasers(state,now,dt,False)
            update_healing(state,now)
            ensure_sword(state)
            for p in ps:
                if p.alive and state['sword'] is not None and p.pos.distance_to(state['sword'])<19 and not p.sword:
                    p.sword=True;state['sword']=None;sfx('pickup')
                    state['fx'].burst(p.pos,GOLD,18,120,40)
                if p.alive and p.sword and p.pos.distance_to(state['boss_pos'])<34:
                    p.sword=False;state['boss_hp']-=1;state['hit_by'][ps.index(p)]+=1
                    state['boss_hurt']=.28;sfx('strike')
                    state['effects'].append(Slash(p.pos,state['boss_pos']))
                    state['fx'].burst(state['boss_pos'],GOLD,60,320,100)
                    state['fx'].shake(10,.28)
                    if state['boss_hp']>0:
                        state['sword']=sword_spawn(ps,state['boss_pos']);sfx('sword_spawn')
                        state['fx'].burst(state['sword'],GOLD,20,100,35)
            if not any(p.alive for p in ps):state['phase']='end';state['message']='GAME OVER'
            elif state['boss_hp']<=0:
                state['fx'].burst(state['boss_pos'],GOLD,150,420,230)
                state['fx'].burst(state['boss_pos'],VIOLET,60,300,180)
                state['fx'].shake(16,.65)
                state['orbs'].clear();state['lasers'].clear();state['ring_at']=None
                state['sword']=None;sfx('phase');state['transition']=.85
                living=[p for p in ps if p.alive]
                if len(living)==1:state['phase']='end';state['message']=living[0].name+' WINS'
                elif ps[0].hp!=ps[1].hp:
                    state['phase']='end';state['message']=max(ps,key=lambda p:p.hp).name+' WINS'
                else:
                    state['phase']='duel';state['next_laser']=now+1.5
                    for p in ps:p.invuln=0
        elif phase=='duel':
            if now>=state['next_laser']:
                state['next_laser']=now+max(.85,1.95-(now/45)*.25)
                horizontal=RNG.choice([True,False])
                coord=RNG.randint((ARENA.top+45 if horizontal else ARENA.left+45),
                                  (ARENA.bottom-45 if horizontal else ARENA.right-45))
                state['lasers'].append(Laser(horizontal,coord,now));sfx('warning')
            update_lasers(state,now,dt,True)
            living=[p for p in ps if p.alive]
            if len(living)<2:
                state['phase']='end'
                if living:state['message']=living[0].name+' WINS'
                else:
                    # Simultaneous hits: fallback to boss contributions; tie remains draw.
                    hits=state['hit_by']
                    state['message']='DRAW' if hits[0]==hits[1] else ('P1 WINS' if hits[0]>hits[1] else 'P2 WINS')
        if state['phase']!='boss':state['healing']=None
        SCREEN.fill(BG)
        for x in range(ARENA.left,ARENA.right,40):pygame.draw.line(SCREEN,(16,26,40),(x,ARENA.top),(x,ARENA.bottom))
        for y in range(ARENA.top,ARENA.bottom,40):pygame.draw.line(SCREEN,(16,26,40),(ARENA.left,y),(ARENA.right,y))
        pygame.draw.rect(SCREEN,DIM,ARENA,2)
        text('P1  '+str(ps[0].hp)+' HP  '+('[INDEX]' if hand_mode else '[WASD]'),36,61,CYAN,SMALL)
        text('P2  '+str(ps[1].hp)+' HP  '+('[INDEX]' if hand_mode else '[ARROWS]'),W-270,61,VIOLET,SMALL)
        draw_skill_hud(ps[0],36,('PINCH','PALM','V') if hand_mode else ('E','Q','F'))
        draw_skill_hud(ps[1],W-490,('PINCH','PALM','V') if hand_mode else ('RCtrl','RShift','Enter'))
        text('R restart    ESC quit',W/2,29,color=(126,145,164),font=SMALL,center=True)
        if state['phase']=='boss':
            stage=boss_stage(state['boss_hp'])
            text('WARDEN / '+BOSS_STAGE_NAMES[stage],W/2,60,GOLD,SMALL,True)
            if state['ring_at'] is not None:
                origin=state['boss_pos']+pygame.Vector2(0,40)
                charge=max(0,min(1,1-(state['ring_at']-now)/.8))
                pygame.draw.circle(SCREEN,RED,origin,int(18+24*charge),2)
                text('BURST',origin.x,origin.y+52,RED,SMALL,True)
            boss_sprite(state['boss_pos'],now,state['boss_hurt'])
            pygame.draw.rect(SCREEN,DIM,(W/2-112,43,224,9))
            pygame.draw.rect(SCREEN,RED,(W/2-110,45,220*max(0,state['boss_hp'])/8,5))
            if state['sword'] is not None:
                x,y=map(int,state['sword']);SCREEN.blit(SWORD_SPRITE,SWORD_SPRITE.get_rect(center=(x,y)))
                pygame.draw.circle(SCREEN,(80,62,35),(x,y),17,1)
            for orb in state['orbs']:orb.draw()
            if state['healing'] is not None:state['healing'].draw(now)
            for laser in state['lasers']:laser.draw(now)
            if state['stage_notice']>0:
                text('PHASE '+str(stage)+' / '+BOSS_STAGE_NAMES[stage],W/2,H-58,GOLD,FONT,True)
        if state['phase']=='duel':
            text('FINAL LASER DUEL',W/2,60,RED,SMALL,True)
            for l in state['lasers']:l.draw(now)
        for p in ps:p.draw()
        if hand_mode and hand_frame and not controls.calibrating:
            for index,target in enumerate(hand_frame.targets):
                if target is None and hand_frame.held[index]:target=controls.targets[index]
                if target and ps[index].alive:
                    color=ps[index].color
                    pygame.draw.circle(SCREEN,color,target,11,1)
                    pygame.draw.line(SCREEN,color,(target[0]-16,target[1]),(target[0]-8,target[1]),1)
                    pygame.draw.line(SCREEN,color,(target[0]+8,target[1]),(target[0]+16,target[1]),1)
        for effect in state['effects']:effect.draw()
        draw_combat_fx(state)
        if state['transition']>0:
            veil=pygame.Surface((W,H),pygame.SRCALPHA);veil.fill((160,185,210,int(state['transition']*60)));SCREEN.blit(veil,(0,0))
        if state['phase']=='end':
            shade=pygame.Surface((W,H),pygame.SRCALPHA);shade.fill((7,11,24,190));SCREEN.blit(shade,(0,0))
            text(state['message'],W/2,H/2-20,WHITE,BIG,True)
            text('PRESS R TO RESTART',W/2,H/2+39,GOLD,SMALL,True)
        if controls:
            if hand_mode:draw_hand_status(controls)
            else:text('KEYBOARD MODE / H resume hands',36,H-27,GOLD,SMALL)
        pygame.display.flip()

def main(argv=None):
    parser=argparse.ArgumentParser(description='Void Pointer: Last Light')
    inputs=parser.add_mutually_exclusive_group()
    inputs.add_argument('--no-camera',action='store_true',help='Play with keyboard only')
    inputs.add_argument('--camera',type=int,default=0,help='Camera device index (default: 0)')
    inputs.add_argument('--camera-url',help='HTTP/MJPEG or RTSP video URL (e.g. iPhone DroidCam)')
    parser.add_argument('--model',type=Path,help='Path to MediaPipe hand_landmarker.task')
    args=parser.parse_args(argv)
    tracker=None
    controls=None
    try:
        if not args.no_camera:
            from hand_control.config import CameraConfig
            from hand_control.tracker import HandTracker
            from hand_control.input import HandControls
            camera=CameraConfig(index=args.camera,source_url=args.camera_url)
            if args.model:camera.model_path=args.model
            tracker=HandTracker(camera)
            controls=HandControls(tracker,ARENA,camera)
            tracker.start()
        reset_and_run(controls)
    finally:
        if tracker:tracker.stop()
        pygame.quit()

if __name__=='__main__':main()
