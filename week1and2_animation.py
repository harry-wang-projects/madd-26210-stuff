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

# Cube size in grid units (so it covers a few boxes)
CUBE_GRID_SIZE = 1.0  # 1 box = 16 px

# Cube movement tuning
MOVE_LERP = True  # smooth within each step

# Trajectory settings - subtle trail effect
TRAJECTORY_COLOR = (100, 255, 100)  # Muted blue-gray, less obvious than white
TRAJECTORY_ALPHA = 100  # Very subtle transparency
MAX_TRAIL_LENGTH = 500  # Limit how many past positions to keep (prevents memory bloat)

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
    #resp = requests.get(url, timeout=20)
    #resp.raise_for_status()
    #img_data = BytesIO(resp.content)

    img = pygame.image.load("./uchicago_map.png").convert()
    # Scale to exact canvas size
    smooth = pygame.transform.smoothscale(img, (w_boxes * box_size, h_boxes * box_size))

    # Pixelate: for each grid box, take a representative color
    pixelated = pygame.Surface((w_boxes * box_size, h_boxes * box_size)).convert()
    pixelated = pixelated.convert()

    for gy in range(h_boxes):
        for gx in range(w_boxes):
            # Sample from center of the corresponding box
            sx = gx * box_size + box_size // 2
            sy = gy * box_size + box_size // 2
            color = smooth.get_at((sx, sy))
            rect = pygame.Rect(gx * box_size, gy * box_size, box_size, box_size)
            pygame.draw.rect(pixelated, color, rect)

    return smooth, pixelated


def blend_pixelated_backdrop(surf_pixelated):
    """
    Optional subtle blending to make it feel more integrated.
    Here we just return the pixelated surface as-is, but you could
    add dithering/glow/etc.
    """
    return surf_pixelated


# -----------------------------
# Cube rendering (simple isometric-ish block)
# -----------------------------
def draw_cube(screen, grid_x, grid_y, cube_grid_size=1.0, height=2.0):
    px = math.ceil(grid_x) * BOX_SIZE
    py = math.ceil(grid_y) * BOX_SIZE
    pygame.draw.rect(screen, (0, 150, 0), (px, py, 16, 16) )


# -----------------------------
# Trajectory rendering
# -----------------------------
def draw_trajectory(screen, trajectory_points, box_size, color, alpha):
    """
    Draw the trajectory trail - past positions the cube occupied.
    Uses small subtle dots or squares at each grid position.
    """
    if len(trajectory_points) < 2:
        return

    # Create a surface for alpha blending
    trail_surface = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)

    # Draw each past position as a small filled rectangle
    # Older positions get slightly more transparent for fade effect
    for i, (gx, gy) in enumerate(trajectory_points):
        # Calculate fade based on age (older = more faded)
        age_ratio = i / len(trajectory_points) if len(trajectory_points) > 1 else 1.0
        point_alpha = int(alpha)  # Newer points are more visible

        px = int(gx * box_size)
        py = int(gy * box_size)

        # Draw a small square at each grid position (slightly smaller than grid cell)
        size = max(2, box_size * 2)
        offset = ((box_size * 2) - size) // 2
        rect = pygame.Rect(px, py, size, size)


        # Use the trajectory color with calculated alpha
        faded_color = (*color, point_alpha)
        pygame.draw.rect(trail_surface, color, rect)

    # Blit the trail surface onto the main screen
    screen.blit(trail_surface, (0, 0))


# -----------------------------
# Movement function: move in a line
# -----------------------------
class LineMover:
    """
    Moves a point (cube) from one grid cell to another along a line.
    - total_time: total duration for the move
    - steps_per_second: how many discrete steps you take (positions update)
    Each step advances the cube by a fixed fraction and optionally renders smoothly.
    """

    def __init__(self, start_cell, end_cell, total_time, steps_per_second=10, grid_snap=False):
        self.start = start_cell
        self.end = end_cell
        self.total_time = max(0.0001, float(total_time))
        self.steps_per_second = steps_per_second
        self.grid_snap = grid_snap

        self.t0 = None
        self.done = False

        self.steps = max(1, int(self.total_time * self.steps_per_second))
        self.current_step = 0

        self.x0, self.y0 = self.start
        self.x1, self.y1 = self.end

        # Precompute per-step increments
        self.dx = (self.x1 - self.x0) / self.steps
        self.dy = (self.y1 - self.y0) / self.steps

        # Current position (float)
        self.x = float(self.x0)
        self.y = float(self.y0)

    def begin(self):
        self.t0 = time.perf_counter()
        self.done = False
        self.current_step = 0
        self.x = float(self.x0)
        self.y = float(self.y0)

    def update(self):
        if self.done:
            return (self.x, self.y)

        if self.t0 is None:
            self.begin()

        now = time.perf_counter()
        elapsed = now - self.t0

        # Determine target progress
        progress = min(1.0, elapsed / self.total_time)

        # Option A: smooth interpolation
        if MOVE_LERP:
            x = self.x0 + (self.x1 - self.x0) * progress
            y = self.y0 + (self.y1 - self.y0) * progress
        else:
            # Option B: discrete step interpolation
            step_float = progress * self.steps
            step_idx = min(self.steps, int(step_float))
            x = self.x0 + self.dx * step_idx
            y = self.y0 + self.dy * step_idx

        # Optional snap to grid cell centers
        if self.grid_snap:
            x = round(x)
            y = round(y)

        self.x, self.y = x, y
        self.done = (progress >= 1.0)

        return (self.x, self.y)


def move_cube_line(start_cell, end_cell, time_per_move, steps_per_second=10, grid_snap=False):
    """
    Requested function:
    - move in a line from one position to another
    - takes a certain amount of time each step/move
    This returns a LineMover you can update each frame.
    """
    mover = LineMover(
        start_cell=start_cell,
        end_cell=end_cell,
        total_time=time_per_move,
        steps_per_second=steps_per_second,
        grid_snap=grid_snap
    )
    mover.begin()
    return mover


# -----------------------------
# Main
# -----------------------------
def main(backdrop_url):
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Pixel Grid Cube Movement")
    clock = pygame.time.Clock()

    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            # Detect KEYDOWN events and print cube coordinates
            if event.type == pygame.KEYDOWN:
                running = False
            
            pygame.display.flip()



    # Load + pixelate backdrop
    try:
        _, pixel_bg = load_backdrop_from_url(backdrop_url, GRID_W, GRID_H, BOX_SIZE)
    except Exception as e:
        print("Failed to load backdrop image. Error:")
        print(e)
        pygame.quit()
        sys.exit(1)

    pixel_bg = blend_pixelated_backdrop(pixel_bg)

    # Initial cube position (grid cell coordinates)
    cube_cell = (5, 5)
    cube_x, cube_y = float(cube_cell[0]), float(cube_cell[1])

    # Trajectory history - stores all past grid positions
    trajectory = []
    last_recorded_pos = None

    # Example path: a loop around the grid corners-ish
    # You can replace this with your own path.
    path = [
        (40, 92), (30, 92), (30, 55), (40, 55), 
        (40, 50), (40, 55), (30, 55), (30, 92), (40, 92)
    ]

    path_index = 0
    mover = None

    # Create first mover (move from current to next)
    def start_next_move(speed):
        nonlocal path_index, mover
        start = path[path_index]
        end = path[(path_index + 1) % len(path)]

        # Keep cube within bounds (defensive)
        sx = max(0, min(GRID_W - 1, start[0]))
        sy = max(0, min(GRID_H - 1, start[1]))
        ex = max(0, min(GRID_W - 1, end[0]))
        ey = max(0, min(GRID_H - 1, end[1]))

        start = (sx, sy)
        end = (ex, ey)
        move_timeneeded = (ey - sy + ex - sx) * 0.1
        if move_timeneeded < 0:
            move_timeneeded = -move_timeneeded

        # Move time per move (you can change)
        mover = move_cube_line(
            start_cell=start,
            end_cell=end,
            time_per_move=move_timeneeded,      # seconds
            steps_per_second=12,
            grid_snap=False
        )
        path_index = (path_index + 1) % len(path)

    start_next_move(1)

    # Precompute a faint grid overlay for "pixelated environment"
    grid_overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    for y in range(GRID_H):
        for x in range(GRID_W):
            # subtle vertical/horizontal feel
            rect = pygame.Rect(x * BOX_SIZE, y * BOX_SIZE, BOX_SIZE, BOX_SIZE)
            # very faint lines / dots
            pygame.draw.rect(grid_overlay, (0, 0, 0, 12), rect, 1)


    running = True

    while running:
        dt = clock.tick(FPS) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            # Detect KEYDOWN events and print cube coordinates
            if event.type == pygame.KEYDOWN:
                # Get current cube grid coordinates
                grid_x = round(cube_x)
                grid_y = round(cube_y)
                pixel_x = int(grid_x * BOX_SIZE)
                pixel_y = int(grid_y * BOX_SIZE)
    
                # Print coordinates with key information
                key_name = pygame.key.name(event.key)
                print(f"KEYDOWN: '{key_name}' (key code: {event.key}) | "
                    f"Grid: ({grid_x}, {grid_y}) | "
                    f"Pixel: ({pixel_x}, {pixel_y})")

        # Update cube position
        if mover is not None:
            cube_x, cube_y = mover.update()

            # Record trajectory - only add if position changed significantly
            current_pos = (round(cube_x), round(cube_y))
            if current_pos != last_recorded_pos:
                trajectory.append(current_pos)
                last_recorded_pos = current_pos

                # Limit trail length to prevent memory issues
                if len(trajectory) > MAX_TRAIL_LENGTH:
                    trajectory.pop(0)  # Remove oldest point

            if mover.done:
                start_next_move(1)

        # Draw
        screen.blit(pixel_bg, (0, 0))
        if BG_PIXEL_BLEND:
            screen.blit(grid_overlay, (0, 0))

        # Draw trajectory trail (subtle, behind the cube)
        draw_trajectory(screen, trajectory, BOX_SIZE, TRAJECTORY_COLOR, TRAJECTORY_ALPHA)

        # Draw cube aligned to grid cells; cube_x/cube_y are floats in grid space
        # We'll subtract half cube size for better centering.
        draw_cube(screen, cube_x - (CUBE_GRID_SIZE - 1.0) * 0.5, cube_y - (CUBE_GRID_SIZE - 1.0) * 0.5, cube_grid_size=CUBE_GRID_SIZE, height=2.0)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    # Provide your backdrop image URL here:
    # Example:
    #   https://example.com/image.png
    if len(sys.argv) >= 2:
        url = sys.argv[1]
    else:
        # If you want, replace this with a real URL so it runs immediately.
        url = "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=800&q=80"

    main(url)