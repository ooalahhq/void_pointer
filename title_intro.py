"""Procedural title sequence; no image or video assets required."""
import math
import random

import pygame
import pygame.freetype

INTRO_DURATION = 6.2
INK = (5, 8, 16)
LIGHT = (231, 241, 244)
ICE = (94, 235, 255)
AMBER = (232, 190, 92)


def ramp(t, start, duration):
    return max(0.0, min(1.0, (t-start)/duration))


class TitleIntro:
    def __init__(self, size):
        self.w, self.h = size
        display = pygame.freetype.SysFont('dejavusans', 86, bold=True)
        subtitle = pygame.freetype.SysFont('consolas', 32)
        self.small = pygame.freetype.SysFont('consolas', 14)
        self.title, _ = display.render('VOID POINTER', LIGHT)
        self.highlight, _ = display.render('VOID POINTER', ICE)
        self.subtitle, _ = subtitle.render('[ LAST LIGHT ]', AMBER)
        rng = random.Random(19)
        self.stars = [(rng.uniform(0, math.tau), rng.uniform(100, self.w*.7),
                       rng.uniform(.3, 1), rng.uniform(0, math.tau)) for _ in range(90)]
        self.layer = pygame.Surface(size, pygame.SRCALPHA)
        self.fade = pygame.Surface(size)
        self.fade.fill(INK)

    def draw(self, screen, t):
        w, h = self.w, self.h
        cx, cy = w/2, h*.46
        screen.fill(INK)
        self.layer.fill((0, 0, 0, 0))
        charge = ramp(t, .15, 1.25)
        reveal = ramp(t, 1.1, .7)
        for angle, radius, brightness, phase in self.stars:
            # Draw dust inward, then send it outward as the title arrives.
            distance = radius*(1-.7*charge)+ramp(t, 1.4, 3.5)*radius*.55
            angle += .025*t
            pos = (cx+math.cos(angle)*distance, cy+math.sin(angle)*distance*.55)
            alpha = int((65+55*math.sin(t+phase))*brightness*charge)
            pygame.draw.circle(self.layer, (*ICE, max(0, alpha)), pos, 1 if brightness<.7 else 2)
        if t<2:
            length = int(w*.36*charge)
            alpha = int(170*charge*(1-ramp(t, 1.4, .6)))
            pygame.draw.line(self.layer, (*ICE, alpha), (cx-length, cy), (cx+length, cy), 2)
        screen.blit(self.layer, (0, 0))

        if reveal:
            ease = 1-(1-reveal)**3
            scale = 1+.18*(1-ease)-.025*ramp(t, 2, 3.1)
            size = (int(self.title.get_width()*scale), int(self.title.get_height()*scale))
            title = pygame.transform.smoothscale(self.title, size)
            title.set_alpha(int(255*reveal))
            rect = title.get_rect(center=(cx, cy))
            # A restrained light echo settles into the solid title.
            echo = pygame.transform.smoothscale(self.highlight, size)
            echo.set_alpha(int(65*(1-reveal)))
            screen.blit(echo, rect.move(int(24*(1-ease)), 0))
            screen.blit(echo, rect.move(-int(24*(1-ease)), 0))
            screen.blit(title, rect)
            sweep = ramp(t, 1.6, 1.5)
            if 0<sweep<1:
                highlight = pygame.transform.smoothscale(self.highlight, size)
                old_clip = screen.get_clip()
                screen.set_clip(pygame.Rect(rect.left+int(rect.width*sweep), rect.top, 18, rect.height))
                screen.blit(highlight, rect)
                screen.set_clip(old_clip)

        sub_reveal = ramp(t, 2, .9)
        if sub_reveal:
            self.subtitle.set_alpha(int(255*sub_reveal))
            rect = self.subtitle.get_rect(center=(cx, cy+94+12*(1-sub_reveal)))
            old_clip = screen.get_clip()
            screen.set_clip(pygame.Rect(cx-rect.width*sub_reveal/2, rect.top,
                                       rect.width*sub_reveal, rect.height))
            screen.blit(self.subtitle, rect)
            screen.set_clip(old_clip)
            half = int(180*sub_reveal)
            pygame.draw.line(screen, AMBER, (cx-half, cy+140), (cx+half, cy+140), 1)

        bars = int(54*(1-ramp(t, 4.8, .8)))
        pygame.draw.rect(screen, (0, 0, 0), (0, 0, w, bars))
        pygame.draw.rect(screen, (0, 0, 0), (0, h-bars, w, bars))
        if t>.7:
            hint, _ = self.small.render('SPACE / ENTER  —  SKIP', (126, 145, 164))
            hint.set_alpha(int(150*ramp(t, .7, .8)))
            screen.blit(hint, hint.get_rect(center=(cx, h-29)))
        fade = ramp(t, 5.1, 1.1)
        if fade:
            self.fade.set_alpha(int(255*fade))
            screen.blit(self.fade, (0, 0))
