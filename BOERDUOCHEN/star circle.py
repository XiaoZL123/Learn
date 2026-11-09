import pygame
import math
import random

# 窗口设置
WIDTH, HEIGHT = 800, 600
pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("星际轨道")
clock = pygame.time.Clock()

# 中心和粒子参数
cx, cy = WIDTH // 2, HEIGHT // 2
num_particles = 200
particles = []

for _ in range(num_particles):
    angle = random.uniform(0, math.pi * 2)
    radius = random.uniform(150, 300)
    speed = random.uniform(0.004, 0.01)
    particles.append([angle, radius, speed])

# 半透明残影层：只创建一次，每帧 blit 上去，旧轨迹会慢慢淡出
trail = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
trail.fill((0, 0, 20, 10))

running = True
while running:
    # 关闭窗口
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # 盖上半透明层，形成轨迹
    screen.blit(trail, (0, 0))

    # 直接更新列表里的 angle，只改副本的话粒子不会转
    for p in particles:
        p[0] = (p[0] + p[2]) % (math.pi * 2)
        angle, radius, _speed = p
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        pygame.draw.circle(screen, (200, 200, 255), (int(x), int(y)), 2)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
