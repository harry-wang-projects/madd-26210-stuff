import pygame
import sys
import math
import time
from io import BytesIO
import requests

# -----------------------------
# Config
# -----------------------------
GRID_W = 100
GRID_H = 100
BOX_SIZE = 8
SCREEN_W = GRID_W * BOX_SIZE
SCREEN_H = GRID_H * BOX_SIZE

BG_PIXEL_BLEND = True
CUBE_COLOR = (255, 255, 255)
CUBE_EDGE = (20, 20, 20)

FPS = 60

# Cube size in grid units
CUBE_GRID_SIZE = 1.0

# Trajectory settings
TRAJECTORY_COLOR = (100, 255, 100)
TRAJECTORY_ALPHA = 180
MAX_TRAIL_LENGTH = 2000

# Mode constants
MODE_RECORD = "record"
MODE_PLAYBACK = "playback"

# Movement speed (cells per second)
MOVE_SPEED = 8.0

# -----------------------------
# Helper: download + scale backdrop into pixelated grid
# -----------------------------
def load_backdrop_from_url(url, w_boxes, h_boxes, box_size):
    """
    Loads an image from a URL, then:
      - scales it to (w_boxes * box_size, h_boxes * box_size)
      - returns both:
          * a smooth scaled surface for internal use
          * a pixelated version quantized to box-level blocks
    """
    img = pygame.image.load("./uchicago_map.png").convert()
    smooth = pygame.transform.smoothscale(img, (w_boxes * box_size, h_boxes * box_size))

    pixelated = pygame.Surface((w_boxes * box_size, h_boxes * box_size)).convert()

    for gy in range(h_boxes):
        for gx in range(w_boxes):
            sx = gx * box_size + box_size // 2
            sy = gy * box_size + box_size // 2
            color = smooth.get_at((sx, sy))
            rect = pygame.Rect(gx * box_size, gy * box_size, box_size, box_size)
            pygame.draw.rect(pixelated, color, rect)

    return smooth, pixelated


def blend_pixelated_backdrop(surf_pixelated):
    return surf_pixelated


# -----------------------------
# Cube rendering
# -----------------------------
def draw_cube(screen, grid_x, grid_y, cube_grid_size=1.0, height=2.0):
    px = math.ceil(grid_x) * BOX_SIZE
    py = math.ceil(grid_y) * BOX_SIZE
    pygame.draw.rect(screen, (0, 200, 100), (px, py, BOX_SIZE, BOX_SIZE))
    # Add a bright center for visibility
    pygame.draw.rect(screen, (150, 255, 150), (px+2, py+2, BOX_SIZE-4, BOX_SIZE-4))


# -----------------------------
# Trajectory rendering
# -----------------------------
def draw_trajectory(screen, trajectory_points, box_size, color, alpha):
    """
    Draw the trajectory trail - only draws the provided points.
    During playback, we only pass the revealed portion.
    """
    if len(trajectory_points) < 1:
        return

    trail_surface = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    
    for i, (gx, gy) in enumerate(trajectory_points):
        # Fade older points
        age_ratio = i / len(trajectory_points) if len(trajectory_points) > 1 else 1.0
        point_alpha = int(alpha * (0.3 + 0.7 * age_ratio))
        
        px = int(gx * box_size)
        py = int(gy * box_size)
        
        size = max(2, box_size - 2)
        offset = (box_size - size) // 2
        rect = pygame.Rect(px + offset, py + offset, size, size)
        
        faded_color = (*color, point_alpha)
        pygame.draw.rect(trail_surface, faded_color, rect)
    
    screen.blit(trail_surface, (0, 0))


# -----------------------------
# Movement class
# -----------------------------
class LineMover:
    def __init__(self, start_cell, end_cell, speed_cells_per_sec):
        self.start = start_cell
        self.end = end_cell
        self.speed = speed_cells_per_sec
        self.t0 = None
        self.done = False
        
        dx = end_cell[0] - start_cell[0]
        dy = end_cell[1] - start_cell[1]
        distance = math.sqrt(dx*dx + dy*dy)
        
        if distance < 0.001:
            self.duration = 0
            self.done = True
        else:
            self.duration = distance / speed_cells_per_sec
            
        self.x0, self.y0 = start_cell
        self.x1, self.y1 = end_cell

    def begin(self):
        self.t0 = time.perf_counter()
        self.done = False

    def update(self):
        if self.done:
            return (self.x1, self.y1)
        
        if self.t0 is None:
            self.begin()
            
        now = time.perf_counter()
        elapsed = now - self.t0
        progress = min(1.0, elapsed / self.duration) if self.duration > 0 else 1.0
        
        # Smooth ease-in-out
        t = progress
        smooth_t = t * t * (3 - 2 * t)
        
        x = self.x0 + (self.x1 - self.x0) * smooth_t
        y = self.y0 + (self.y1 - self.y0) * smooth_t
        
        if progress >= 1.0:
            self.done = True
            x, y = self.x1, self.y1
            
        return (x, y)
    
    def get_progress(self):
        """Returns 0.0 to 1.0 of how far along the move we are"""
        if self.t0 is None:
            return 0.0
        if self.done:
            return 1.0
        now = time.perf_counter()
        elapsed = now - self.t0
        return min(1.0, elapsed / self.duration) if self.duration > 0 else 1.0


# -----------------------------
# Main
# -----------------------------
def main(backdrop_url):
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Grid Recorder - Arrows to Move, SPACE to Playback")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 24)

    # Load backdrop
    try:
        _, pixel_bg = load_backdrop_from_url(backdrop_url, GRID_W, GRID_H, BOX_SIZE)
    except Exception as e:
        print("Failed to load backdrop image. Error:")
        print(e)
        pygame.quit()
        sys.exit(1)

    pixel_bg = blend_pixelated_backdrop(pixel_bg)

    # Grid overlay
    grid_overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    for y in range(GRID_H):
        for x in range(GRID_W):
            rect = pygame.Rect(x * BOX_SIZE, y * BOX_SIZE, BOX_SIZE, BOX_SIZE)
            pygame.draw.rect(grid_overlay, (0, 0, 0, 12), rect, 1)

    # State variables
    mode = MODE_RECORD
    
    # Recording state
    cube_cell = (GRID_W // 2, GRID_H // 2)
    cube_x, cube_y = float(cube_cell[0]), float(cube_cell[1])
    recorded_path = [cube_cell]  # Start with initial position
    current_mover = None
    input_cooldown = 0  # Prevent accidental double-moves
    
    # Playback state
    playback_index = 0
    playback_mover = None
    revealed_trajectory = []  # Only the portion revealed so far
    last_revealed_pos = None
    
    running = True

    while running:
        dt = clock.tick(FPS) / 1000.0
        if input_cooldown > 0:
            input_cooldown -= dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                
                # Switch modes with SPACE
                if event.key == pygame.K_SPACE:
                    if mode == MODE_RECORD and len(recorded_path) > 1:
                        mode = MODE_PLAYBACK
                        playback_index = 0
                        revealed_trajectory = [recorded_path[0]]
                        last_revealed_pos = recorded_path[0]
                        cube_x, cube_y = float(recorded_path[0][0]), float(recorded_path[0][1])
                        # Start first move
                        if len(recorded_path) > 1:
                            playback_mover = LineMover(
                                recorded_path[0], 
                                recorded_path[1], 
                                MOVE_SPEED
                            )
                            playback_mover.begin()
                    elif mode == MODE_PLAYBACK:
                        # Reset to record mode
                        mode = MODE_RECORD
                        recorded_path = [(round(cube_x), round(cube_y))]
                        revealed_trajectory = []
                        current_mover = None
                        playback_mover = None
                
                # Arrow key handling in RECORD mode
                if mode == MODE_RECORD and input_cooldown <= 0:
                    dx, dy = 0, 0
                    if event.key == pygame.K_UP:
                        dy = -1
                    elif event.key == pygame.K_DOWN:
                        dy = 1
                    elif event.key == pygame.K_LEFT:
                        dx = -1
                    elif event.key == pygame.K_RIGHT:
                        dx = 1
                    
                    if dx != 0 or dy != 0:
                        current_cell = (round(cube_x), round(cube_y))
                        target_cell = (
                            max(0, min(GRID_W - 1, current_cell[0] + dx)),
                            max(0, min(GRID_H - 1, current_cell[1] + dy))
                        )
                        
                        # Only move if actually changing cell
                        if target_cell != current_cell:
                            current_mover = LineMover(current_cell, target_cell, MOVE_SPEED * 2)
                            current_mover.begin()
                            input_cooldown = 0.1  # 100ms cooldown

        # UPDATE LOGIC
        if mode == MODE_RECORD:
            # Handle movement
            if current_mover is not None:
                cube_x, cube_y = current_mover.update()
                
                # Record position when we enter a new grid cell
                current_pos = (round(cube_x), round(cube_y))
                if recorded_path[-1] != current_pos:
                    recorded_path.append(current_pos)
                    
                if current_mover.done:
                    current_mover = None
                    
        elif mode == MODE_PLAYBACK:
            if playback_mover is not None:
                cube_x, cube_y = playback_mover.update()
                
                # Reveal trajectory as we move
                current_pos = (round(cube_x), round(cube_y))
                if last_revealed_pos is None or current_pos != last_revealed_pos:
                    revealed_trajectory.append(current_pos)
                    last_revealed_pos = current_pos
                
                if playback_mover.done:
                    playback_index += 1
                    if playback_index < len(recorded_path) - 1:
                        # Start next segment
                        start = recorded_path[playback_index]
                        end = recorded_path[playback_index + 1]
                        playback_mover = LineMover(start, end, MOVE_SPEED)
                        playback_mover.begin()
                    else:
                        # Playback finished - loop or stop? Let's stop at end
                        playback_mover = None

        # DRAWING
        screen.blit(pixel_bg, (0, 0))
        if BG_PIXEL_BLEND:
            screen.blit(grid_overlay, (0, 0))

        if mode == MODE_RECORD:
            # Draw full recorded path so far (semi-transparent)
            draw_trajectory(screen, recorded_path, BOX_SIZE, (100, 100, 255), 80)
            
            # Instructions
            text = font.render("RECORD MODE - Arrows to move | SPACE to playback", True, (255, 255, 255))
            screen.blit(text, (10, 10))
            
            points_text = font.render(f"Points: {len(recorded_path)}", True, (255, 255, 255))
            screen.blit(points_text, (10, 30))
            
        elif mode == MODE_PLAYBACK:
            # Only draw revealed trajectory (the slow reveal effect)
            draw_trajectory(screen, revealed_trajectory, BOX_SIZE, TRAJECTORY_COLOR, TRAJECTORY_ALPHA)
            
            # Instructions
            if playback_mover is None and playback_index >= len(recorded_path) - 1:
                text = font.render("PLAYBACK COMPLETE - SPACE to record again", True, (255, 255, 255))
            else:
                text = font.render("PLAYBACK MODE - SPACE to restart", True, (255, 255, 255))
            screen.blit(text, (10, 10))
            
            progress = min(100, int(100 * (playback_index + 1) / max(1, len(recorded_path) - 1)))
            prog_text = font.render(f"Progress: {progress}%", True, (255, 255, 255))
            screen.blit(prog_text, (10, 30))

        # Draw cube
        draw_cube(screen, cube_x - (CUBE_GRID_SIZE - 1.0) * 0.5, 
                 cube_y - (CUBE_GRID_SIZE - 1.0) * 0.5, 
                 cube_grid_size=CUBE_GRID_SIZE)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        url = sys.argv[1]
    else:
        url = "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=800&q=80"
    main(url)