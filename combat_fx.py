"""Bounded visual effects, isolated from gameplay randomness and collision logic."""
import math
import random
import pygame


class CombatFX:
    MAX_PARTICLES = 650
    MAX_RINGS = 24

    def __init__(self, size):
        self.rng = random.Random()
        self.particles = []
        self.rings = []
        self.layer = pygame.Surface(size)
        self.shake_time = 0
        self.shake_duration = 1
        self.shake_power = 0

    def shake(self, power, duration=.25):
        self.shake_power = min(18, max(self.shake_power, power))
        self.shake_time = max(self.shake_time, duration)
        self.shake_duration = self.shake_time

    def burst(self, pos, color, count=24, speed=200, radius=65):
        for _ in range(count):
            velocity = pygame.Vector2(1, 0).rotate(self.rng.uniform(0, 360))
            velocity *= self.rng.uniform(speed*.25, speed)
            life = self.rng.uniform(.25, .65)
            self.particles.append([pygame.Vector2(pos), velocity, life, life, color,
                                   self.rng.uniform(2, 5)])
        self.particles = self.particles[-self.MAX_PARTICLES:]
        if radius:
            self.rings.append([pygame.Vector2(pos), .45, .45, radius, color])
            self.rings = self.rings[-self.MAX_RINGS:]

    def trail(self, pos, color, size=8):
        self.particles.append([pygame.Vector2(pos), pygame.Vector2(), .22, .22, color, size])
        self.particles = self.particles[-self.MAX_PARTICLES:]

    def update(self, dt):
        self.shake_time = max(0, self.shake_time-dt)
        if not self.shake_time:self.shake_power = 0
        for particle in self.particles:
            particle[0] += particle[1]*dt
            particle[1] *= math.exp(-3*dt)
            particle[2] = max(0, particle[2]-dt)
        self.particles = [p for p in self.particles if p[2]>0]
        for ring in self.rings:ring[1] = max(0, ring[1]-dt)
        self.rings = [ring for ring in self.rings if ring[1]>0]

    def offset(self):
        if self.shake_time<=0:return (0, 0)
        amplitude = self.shake_power*(self.shake_time/self.shake_duration)**2
        return (round(self.rng.uniform(-amplitude, amplitude)),
                round(self.rng.uniform(-amplitude, amplitude)))

    def draw(self, target):
        self.layer.fill((0, 0, 0))
        for pos, _, life, duration, color, size in self.particles:
            fade = life/duration
            radius = max(1, int(size*fade))
            pygame.draw.circle(self.layer, tuple(int(c*.12*fade) for c in color), pos, radius*3)
            pygame.draw.circle(self.layer, tuple(int(c*.65*fade) for c in color), pos, radius)
            pygame.draw.circle(self.layer, tuple(int(220*fade) for _ in color), pos, 1)
        for pos, life, duration, radius, color in self.rings:
            progress = 1-life/duration
            pygame.draw.circle(self.layer, tuple(int(c*(1-progress)) for c in color),
                               pos, max(1, int(8+radius*progress)), max(1, int(4*(1-progress))))
        target.blit(self.layer, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
