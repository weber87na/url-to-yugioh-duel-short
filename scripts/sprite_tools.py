"""Isolate registered sprite components for composition without changing atlases.

Requires Pillow, numpy, opencv-python. Coordinates are in the full RGBA atlas.
Returns a new cropped image plus audit metadata. This is not anatomy repair.
"""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def isolate_pose(sheet, bounds, seed_points, alpha_threshold=128, fringe=1):
    """Keep explicitly selected components, including separate registered props.

    bounds=(left, top, right, bottom), right/bottom exclusive; each seed is (x,y).
    Reject bounds that cut a selected opaque component. Padding must be supplied
    by the caller when antialiased edges need extra room. Never selects by size.
    """
    if sheet.mode != 'RGBA':
        raise ValueError('Expected an RGBA atlas with real transparency')
    if len(bounds) != 4 or any(int(v) != v for v in bounds):
        raise ValueError('bounds must contain four integer coordinates')
    x0, y0, x1, y1 = map(int, bounds)
    if not (0 <= x0 < x1 <= sheet.width and 0 <= y0 < y1 <= sheet.height):
        raise ValueError('bounds outside atlas')
    if not (0 <= alpha_threshold < 255 and 0 <= fringe <= 4 and int(fringe) == fringe):
        raise ValueError('Invalid alpha threshold or fringe radius (0..4)')
    alpha = np.asarray(sheet.getchannel('A'))
    if alpha.min() == 255:
        raise ValueError('Atlas has no transparent background')
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        (alpha > alpha_threshold).astype('uint8'), connectivity=8)
    selected = set()
    for point in seed_points:
        if len(point) != 2 or any(int(v) != v for v in point):
            raise ValueError('Each seed must be an integer (x, y)')
        x, y = map(int, point)
        if not (x0 <= x < x1 and y0 <= y < y1) or labels[y, x] == 0:
            raise ValueError(f'Seed {point} is outside bounds or below alpha threshold')
        selected.add(int(labels[y, x]))
    if not selected:
        raise ValueError('At least one verified component seed is required')
    for label in selected:
        left, top, width, height, _ = map(int, stats[label])
        if not (x0 <= left and y0 <= top and left+width <= x1 and top+height <= y1):
            raise ValueError('Selected component crosses bounds: enlarge registration or fix touching poses')
    local_labels = labels[y0:y1, x0:x1]
    selected_mask = np.isin(local_labels, list(selected))
    keep = selected_mask.copy()
    if fringe:
        radius = int(fringe)
        edge = cv2.dilate(selected_mask.astype('uint8'), np.ones((2*radius+1, 2*radius+1), 'uint8')) > 0
        keep |= edge & (local_labels == 0)
    local_alpha = alpha[y0:y1, x0:x1]
    result = sheet.crop((x0, y0, x1, y1))
    result.putalpha(Image.fromarray(np.where(keep, local_alpha, 0).astype('uint8')))
    audit = {
        'bounds': [x0, y0, x1, y1], 'selected_components': sorted(selected),
        'selected_opaque_pixels': int(selected_mask.sum()),
        'foreign_opaque_pixels_excluded': int(((local_labels > 0) & ~selected_mask).sum()),
        'original_edge_alpha_preserved': True,
        'alpha_threshold': alpha_threshold, 'fringe': fringe,
    }
    return result, audit
