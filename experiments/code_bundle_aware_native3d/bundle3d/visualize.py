"""Visualisation of automatic bundle grouping (P0) and planning results."""
from __future__ import annotations

import math
from collections import Counter

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

BOARD = 150.0
KIND_COLORS = {'opposite': '#1f6fd6', 'same': '#e07b1a', 'adjacent': '#2f9e44'}
PLANE_COLORS = {'z1': '#1f6fd6', 'z2': '#e07b1a'}


def _bundle_colors(count):
    cmap = plt.get_cmap('tab20')
    combined = []
    for index in range(20):
        combined.append(cmap(index))
    extra = plt.get_cmap('tab20b')
    for index in range(20):
        combined.append(extra(index))
    extra2 = plt.get_cmap('tab20c')
    for index in range(20):
        combined.append(extra2(index))
    return [combined[index % len(combined)] for index in range(count)]


def _draw_board(ax, title):
    ax.add_patch(Rectangle((0, 0), BOARD, BOARD, fill=False, lw=1.2,
                           color='#495057'))
    for x in range(0, 151, 25):
        ax.axvline(x, color='#e9ecef', lw=0.5, zorder=0)
        ax.axhline(x, color='#e9ecef', lw=0.5, zorder=0)
    ax.set_xlim(-4, BOARD + 4)
    ax.set_ylim(-4, BOARD + 4)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title(title, fontsize=9)


def figure_topology_raw(features, path):
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 6.4))
    for ax, plane in zip(axes, ('z1', 'z2')):
        others = [feature for feature in features if feature['plane'] == plane]
        for feature in others:
            start, end = feature['start_xy'], feature['end_xy']
            ax.plot([start[0], end[0]], [start[1], end[1]],
                    color=KIND_COLORS.get(feature['kind'], '#868e96'),
                    lw=0.6, alpha=0.65)
        for kind, color in KIND_COLORS.items():
            ax.plot([], [], color=color, lw=1.2, label=kind)
        ax.legend(fontsize=7, loc='upper left')
        _draw_board(ax, f'raw 1024-connection topology ({plane})')
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def figure_bundle_grouping(orbits, bundles_by_plane, path, title_suffix=''):
    planes = sorted(bundles_by_plane)
    fig, axes = plt.subplots(1, len(planes), figsize=(6.4 * len(planes), 6.4))
    if len(planes) == 1:
        axes = [axes]
    for ax, plane in zip(axes, planes):
        bundles = bundles_by_plane[plane]
        colors = _bundle_colors(len(bundles))
        orbit_by_id = {int(orbit['orbit_id']): orbit
                       for orbit in orbits if orbit['plane'] == plane}
        for bundle_id, bundle in enumerate(bundles):
            for orbit_id in bundle['orbit_ids']:
                orbit = orbit_by_id[int(orbit_id)]
                for member in orbit['members']:
                    start, end = member['start_xy'], member['end_xy']
                    ax.plot([start[0], end[0]], [start[1], end[1]],
                            color=colors[bundle_id], lw=0.8, alpha=0.8)
        for bundle_id, bundle in enumerate(bundles):
            centre = bundle['bbox']['centre']
            ax.text(centre[0], centre[1], str(bundle_id), fontsize=5.5,
                    ha='center', va='center', color='black',
                    bbox=dict(boxstyle='round,pad=0.1', fc='white',
                              ec=colors[bundle_id], alpha=0.75, lw=0.6))
        _draw_board(ax, f'{plane}: {len(bundles)} automatic bundles'
                        f'{title_suffix}')
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def figure_bundle_corridors(orbits, bundles_by_plane, path):
    planes = sorted(bundles_by_plane)
    fig, axes = plt.subplots(1, len(planes), figsize=(6.4 * len(planes), 6.4))
    if len(planes) == 1:
        axes = [axes]
    for ax, plane in zip(axes, planes):
        bundles = bundles_by_plane[plane]
        colors = _bundle_colors(len(bundles))
        orbit_by_id = {int(orbit['orbit_id']): orbit
                       for orbit in orbits if orbit['plane'] == plane}
        for bundle_id, bundle in enumerate(bundles):
            bbox = bundle['bbox']
            ax.add_patch(Rectangle(
                (bbox['min_x'] - 1, bbox['min_y'] - 1),
                bbox['max_x'] - bbox['min_x'] + 2,
                bbox['max_y'] - bbox['min_y'] + 2,
                fill=True, alpha=0.12, edgecolor=colors[bundle_id], lw=1.0))
            for orbit_id in bundle['orbit_ids']:
                for member in orbit_by_id[int(orbit_id)]['members']:
                    start, end = member['start_xy'], member['end_xy']
                    ax.plot([start[0], end[0]], [start[1], end[1]],
                            color=colors[bundle_id], lw=0.4, alpha=0.35)
            ax.text(bbox['min_x'], max(bbox['min_y'], 2),
                    str(bundle_id), fontsize=5, color=colors[bundle_id])
        _draw_board(ax, f'{plane}: bundle corridors (bbox + members)')
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def figure_bundle_zoom(orbits, bundles_by_plane, path, plane='z2',
                       regions=None):
    regions = regions or [
        ('NE corner / adjacent area', 85, 150, 85, 150),
        ('N edge / U bundles', 35, 105, 132, 150),
        ('board centre corridors', 55, 95, 55, 95),
        ('SW corner / adjacent area', 0, 55, 0, 55),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12.2, 11.6))
    bundles = bundles_by_plane[plane]
    colors = _bundle_colors(len(bundles))
    orbit_by_id = {int(orbit['orbit_id']): orbit
                   for orbit in orbits if orbit['plane'] == plane}
    for ax, (name, x0, x1, y0, y1) in zip(axes.ravel(), regions):
        for bundle_id, bundle in enumerate(bundles):
            bbox = bundle['bbox']
            if bbox['max_x'] < x0 or bbox['min_x'] > x1 or \
                    bbox['max_y'] < y0 or bbox['min_y'] > y1:
                continue
            ax.add_patch(Rectangle(
                (bbox['min_x'], bbox['min_y']),
                bbox['max_x'] - bbox['min_x'], bbox['max_y'] - bbox['min_y'],
                fill=True, alpha=0.10, edgecolor=colors[bundle_id], lw=0.9))
            for orbit_id in bundle['orbit_ids']:
                orbit = orbit_by_id[int(orbit_id)]
                for member in orbit['members']:
                    start, end = member['start_xy'], member['end_xy']
                    if not (x0 - 15 <= start[0] <= x1 + 15
                            or x0 - 15 <= end[0] <= x1 + 15):
                        continue
                    ax.plot([start[0], end[0]], [start[1], end[1]],
                            color=colors[bundle_id], lw=0.9, alpha=0.8)
                    ax.text(start[0], start[1], str(member['route_id']),
                            fontsize=3.4, color='#495057', alpha=0.9)
            ax.text(bbox['min_x'], bbox['min_y'], str(bundle_id),
                    fontsize=5, color=colors[bundle_id])
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect('equal')
        ax.set_title(f'{plane}: {name}', fontsize=9)
        ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(path, dpi=175)
    plt.close(fig)


def figure_compatibility_heatmap(orbits, adjacency, bundles_by_plane, path):
    planes = sorted(bundles_by_plane)
    fig, axes = plt.subplots(1, len(planes), figsize=(6.4 * len(planes), 5.8))
    if len(planes) == 1:
        axes = [axes]
    for ax, plane in zip(axes, planes):
        bundles = bundles_by_plane[plane]
        order = [orbit_id for bundle in bundles
                 for orbit_id in bundle['orbit_ids']]
        position = {orbit_id: index for index, orbit_id in enumerate(order)}
        size = len(order)
        matrix = np.zeros((size, size), dtype=float)
        for orbit_id in order:
            for neighbour, weight in adjacency.get(int(orbit_id), {}).items():
                if neighbour in position:
                    matrix[position[orbit_id], position[neighbour]] = weight
        image = ax.imshow(matrix, cmap='viridis', vmin=0.0, vmax=1.0,
                          interpolation='nearest')
        boundaries = []
        cursor = 0
        for bundle in bundles:
            cursor += bundle['size_orbits']
            boundaries.append(cursor)
        for boundary in boundaries[:-1]:
            ax.axhline(boundary - 0.5, color='white', lw=0.4)
            ax.axvline(boundary - 0.5, color='white', lw=0.4)
        ax.set_title(f'{plane}: compatibility matrix ordered by final bundles',
                     fontsize=9)
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.03)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def figure_bundle_representatives(orbits, bundles_by_plane, path):
    """One representative connection per C4 orbit, coloured by bundle.

    This shows the spatial structure of the automatic grouping in the fundamental
    domain (each orbit contributes one canonical connection) instead of the fully
    C4-replicated 1024 lines.
    """
    planes = sorted(bundles_by_plane)
    fig, axes = plt.subplots(1, len(planes), figsize=(6.4 * len(planes), 6.4))
    if len(planes) == 1:
        axes = [axes]
    for ax, plane in zip(axes, planes):
        bundles = bundles_by_plane[plane]
        colors = _bundle_colors(len(bundles))
        orbit_by_id = {int(orbit['orbit_id']): orbit
                       for orbit in orbits if orbit['plane'] == plane}
        for bundle_id, bundle in enumerate(bundles):
            for orbit_id in bundle['orbit_ids']:
                orbit = orbit_by_id[int(orbit_id)]
                member = orbit['members'][0]
                start, end = member['start_xy'], member['end_xy']
                ax.plot([start[0], end[0]], [start[1], end[1]],
                        color=colors[bundle_id], lw=1.4, alpha=0.9)
                ax.plot([start[0]], [start[1]], marker='o', ms=1.6,
                        color=colors[bundle_id])
            centre = bundle['bbox']['centre']
            ax.text(centre[0], centre[1], str(bundle_id), fontsize=6.5,
                    ha='center', va='center',
                    bbox=dict(boxstyle='round,pad=0.12', fc='white',
                              ec=colors[bundle_id], alpha=0.85, lw=0.7))
        _draw_board(ax, f'{plane}: one representative connection per orbit '
                        f'({len(bundles)} bundles)')
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def figure_bundle_stats(methods, path):
    """methods: {name: summary dict}."""
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.4))
    names = list(methods)
    positions = np.arange(len(names))
    axes[0].bar(positions, [methods[name]['bundle_count'] for name in names],
                color='#1971c2')
    axes[0].set_xticks(positions, names, rotation=12)
    axes[0].set_ylabel('bundle count')
    axes[0].set_title('automatic bundle count')
    axes[0].grid(alpha=0.2, axis='y')
    axes[1].bar(positions, [methods[name]['size_orbits']['mean']
                            for name in names], color='#2f9e44')
    axes[1].set_xticks(positions, names, rotation=12)
    axes[1].set_ylabel('mean orbits / bundle')
    axes[1].set_title('bundle size (orbit = 4 connections)')
    axes[1].grid(alpha=0.2, axis='y')
    axes[2].bar(positions, [methods[name]['internal_cross_rate'] for name in names],
                color='#e8590c')
    axes[2].set_xticks(positions, names, rotation=12)
    axes[2].set_ylabel('internal crossing rate')
    axes[2].set_title('internal straight-chord crossings per pair')
    axes[2].grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(path, dpi=175)
    plt.close(fig)


def figure_bundle_kind_mix(bundles_by_plane, path):
    planes = sorted(bundles_by_plane)
    fig, axes = plt.subplots(1, len(planes), figsize=(6.6 * len(planes), 4.4))
    if len(planes) == 1:
        axes = [axes]
    kinds = ['opposite', 'same', 'adjacent']
    kind_colors = KIND_COLORS
    for ax, plane in zip(axes, planes):
        bundles = bundles_by_plane[plane]
        counts = {kind: [] for kind in kinds}
        for bundle in bundles:
            for kind in kinds:
                counts[kind].append(bundle['kind_mix'].get(kind, 0))
        bottom = np.zeros(len(bundles))
        for kind in kinds:
            values = np.array(counts[kind])
            ax.bar(np.arange(len(bundles)), values, bottom=bottom,
                   color=kind_colors[kind], label=kind)
            bottom += values
        ax.set_title(f'{plane}: orbit-kind composition per bundle', fontsize=9)
        ax.set_xlabel('bundle id')
        ax.set_ylabel('orbits')
        ax.legend(fontsize=7)
        ax.grid(alpha=0.2, axis='y')
    fig.tight_layout()
    fig.savefig(path, dpi=175)
    plt.close(fig)
