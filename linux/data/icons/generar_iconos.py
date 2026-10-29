"""Genera los iconos de Hi Claude!: el normal y la variante monocroma para el tema YAMIS.

    python3 generar_iconos.py   (escribe los .svg en esta carpeta)
"""
import math, sys
def burst_hand(cx, cy, s, color, rot=-12):
    # (ángulo desde la vertical, largo, grosor): dedos largos arriba, pulgar a la izquierda,
    # rayos cortos abajo que forman la palma: un estallido que saluda
    rays = [(-34, 50, 10), (-12, 58, 10.5), (10, 55, 10.5), (31, 45, 10),   # dedos
            (-78, 38, 10),                                                   # pulgar
            (62, 22, 9), (95, 25, 9), (125, 27, 9), (152, 28, 9.5), (180, 28, 9.5),
            (208, 27, 9), (236, 25, 9), (-108, 24, 9)]                       # palma
    out = [f'<g transform="rotate({rot} {cx} {cy})" stroke="{color}" stroke-linecap="round">']
    out.append(f'<circle cx="{cx}" cy="{cy}" r="{15*s}" fill="{color}" stroke="none"/>')
    for ang, ln, w in rays:
        a = math.radians(ang)
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{cx+math.sin(a)*ln*s:.1f}" y2="{cy-math.cos(a)*ln*s:.1f}" stroke-width="{w*s}"/>')
    out.append('</g>')
    ox, oy = cx + 2*s, cy - 4*s
    for ang, r1, r2 in [(34, 62, 72), (54, 58, 69), (74, 56, 65)]:
        a = math.radians(ang)
        out.append(f'<line x1="{ox+math.sin(a)*r1*s:.1f}" y1="{oy-math.cos(a)*r1*s:.1f}" x2="{ox+math.sin(a)*r2*s:.1f}" y2="{oy-math.cos(a)*r2*s:.1f}" stroke="{color}" stroke-width="{5.5*s}" stroke-linecap="round"/>')
    return "\n  ".join(out)

normal = f'''<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#faf6f0"/><stop offset="1" stop-color="#efe6da"/></linearGradient>
  </defs>
  <rect x="8" y="12" width="112" height="108" rx="28" fill="#cdbca8"/>
  <rect x="8" y="8" width="112" height="108" rx="28" fill="url(#bg)"/>
  {burst_hand(58, 70, 0.78, "#d97757")}
</svg>'''
mono = f'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 128 128">
  <defs><style id="current-color-scheme" type="text/css">.ColorScheme-Text {{color:#d8dee9}}</style></defs>
  <g class="ColorScheme-Text" color="#d8dee9">
  {burst_hand(56, 72, 0.92, "currentColor")}
  </g>
</svg>'''
open("io.github.HiClaude.svg", "w").write(normal)
open("io.github.HiClaude-yamis.svg", "w").write(mono)
