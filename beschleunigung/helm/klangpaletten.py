"""Klangpaletten für die Ball-Installation als Helm-Presets.

Erzeugt fünf Paletten mit je sechs Bällen:
    Ball-Klaenge/<Palette>/<Ball>.helm     einzelne Presets
    Ball-Klaenge.helmbank                  alles als Bank (in Helm: Browse → Import Bank)
    paletten.json                          dieselben Daten für die Hörseite

    python beschleunigung/helm/klangpaletten.py

Parameterbereiche stammen aus Helms Quellcode (src/common/helm_common.cpp).
Zeiten (Hüllkurven) speichert Helm als Wurzel der Sekunden, Lautstärken als
Wurzel des Pegels, Frequenzen von LFO/Delay als log2(Hz).

Drehung → Mod-Rad: In ball.py bzw. auf der Zuordnungsseite „Drehung → Vibrato“
wählen. Das schickt CC 1, in Helm das Mod-Rad. Jedes Preset hat das Mod-Rad mit
der Eigenschaft belegt, die zum Ball passt (Wind, Rauheit, Helligkeit …).
"""

import json
import math
import os
import zipfile

HIER = os.path.dirname(os.path.abspath(__file__))
BANK = "Ball-Klaenge"

# name: (min, max, schritte, standard) – schritte > 0 heißt ganzzahlig
PARAMETER = {
    "amp_attack": (0, 4, 0, 0.109545), "amp_decay": (0, 4, 0, 1.5), "amp_release": (0, 4, 0, 0.3),
    "amp_sustain": (0, 1, 0, 1.0),
    "arp_frequency": (-1, 4, 0, 2.0), "arp_gate": (0, 1, 0, 0.5), "arp_octaves": (1, 4, 4, 1),
    "arp_on": (0, 1, 2, 0), "arp_pattern": (0, 4, 5, 0), "arp_sync": (0, 3, 4, 1), "arp_tempo": (0, 11, 12, 9),
    "beats_per_minute": (0.333333333, 5, 0, 2.0), "cross_modulation": (0, 0.5, 0, 0.0),
    "cutoff": (28, 127, 0, 80.0),
    "delay_dry_wet": (0, 1, 0, 0.5), "delay_feedback": (-1, 1, 0, 0.4), "delay_frequency": (-2, 5, 0, 2.0),
    "delay_on": (0, 1, 2, 0), "delay_sync": (0, 3, 4, 1), "delay_tempo": (0, 11, 12, 9),
    "distortion_on": (0, 1, 2, 0), "distortion_type": (0, 3, 4, 0), "distortion_drive": (-30, 30, 0, 0.0),
    "distortion_mix": (0, 1, 0, 1.0),
    "fil_attack": (0, 4, 0, 0.0), "fil_decay": (0, 4, 0, 1.5), "fil_env_depth": (-128, 128, 0, 0.0),
    "fil_release": (0, 4, 0, 1.5), "fil_sustain": (0, 1, 0, 0.5),
    "filter_drive": (-12, 20, 0, 0.0), "filter_blend": (0, 2, 0, 0.0), "filter_style": (0, 2, 3, 0),
    "filter_shelf": (0, 2, 3, 0), "filter_on": (0, 1, 2, 0),
    "formant_on": (0, 1, 2, 0), "formant_x": (0, 1, 0, 0.5), "formant_y": (0, 1, 0, 0.5),
    "keytrack": (-1, 1, 0, 0.0), "legato": (0, 1, 2, 0),
    "mod_attack": (0, 4, 0, 0.0), "mod_decay": (0, 4, 0, 1.5), "mod_release": (0, 4, 0, 1.5),
    "mod_sustain": (0, 1, 0, 0.5),
    "mono_lfo_1_amplitude": (-1, 1, 0, 1.0), "mono_lfo_1_frequency": (-7, 6, 0, 1.0),
    "mono_lfo_1_retrigger": (0, 2, 3, 2), "mono_lfo_1_sync": (0, 3, 4, 1), "mono_lfo_1_tempo": (0, 11, 12, 6),
    "mono_lfo_1_waveform": (0, 12, 13, 0),
    "mono_lfo_2_amplitude": (-1, 1, 0, 1.0), "mono_lfo_2_frequency": (-7, 6, 0, 1.0),
    "mono_lfo_2_retrigger": (0, 2, 3, 2), "mono_lfo_2_sync": (0, 3, 4, 1), "mono_lfo_2_tempo": (0, 11, 12, 7),
    "mono_lfo_2_waveform": (0, 12, 13, 0),
    "noise_volume": (0, 1, 0, 0.0), "num_steps": (1, 32, 32, 8),
    "osc_1_transpose": (-48, 48, 97, 0), "osc_1_tune": (-1, 1, 0, 0.0), "osc_1_unison_detune": (0, 100, 0, 10.0),
    "osc_1_unison_voices": (1, 15, 8, 1), "osc_1_volume": (0, 1, 0, 0.5477225575), "osc_1_waveform": (0, 10, 11, 4),
    "osc_2_transpose": (-48, 48, 97, 0), "osc_2_tune": (-1, 1, 0, 0.0), "osc_2_unison_detune": (0, 100, 0, 10.0),
    "osc_2_unison_voices": (1, 15, 8, 1), "osc_2_volume": (0, 1, 0, 0.5477225575), "osc_2_waveform": (0, 10, 11, 4),
    "osc_feedback_amount": (-1, 1, 0, 0.0), "osc_feedback_transpose": (-24, 24, 49, 0),
    "osc_feedback_tune": (-1, 1, 0, 0.0),
    "pitch_bend_range": (0, 48, 49, 2),
    "poly_lfo_amplitude": (-1, 1, 0, 1.0), "poly_lfo_frequency": (-7, 6, 0, 1.0), "poly_lfo_sync": (0, 3, 4, 1),
    "poly_lfo_tempo": (0, 11, 12, 7), "poly_lfo_waveform": (0, 12, 13, 0),
    "polyphony": (1, 32, 32, 4), "portamento": (-9, -1, 0, -7.0), "portamento_type": (0, 2, 3, 0),
    "resonance": (0, 1, 0, 0.5),
    "reverb_damping": (0, 1, 0, 0.5), "reverb_dry_wet": (0, 1, 0, 0.5), "reverb_feedback": (0.8, 1, 0, 0.9),
    "reverb_on": (0, 1, 2, 0),
    "step_frequency": (-5, 6, 0, 2.0), "step_sequencer_retrigger": (0, 2, 3, 2), "step_sequencer_sync": (0, 3, 4, 1),
    "step_sequencer_tempo": (0, 11, 12, 7), "step_smoothing": (0, 0.5, 0, 0.0),
    "stutter_frequency": (0, 7, 0, 3.0), "stutter_sync": (0, 3, 4, 1), "stutter_tempo": (6, 11, 6, 8),
    "stutter_on": (0, 1, 2, 0), "stutter_resample_frequency": (-7, 4, 0, 1.0), "stutter_resample_sync": (0, 3, 4, 1),
    "stutter_resample_tempo": (0, 11, 12, 6), "stutter_softness": (0, 1, 0, 0.2),
    "sub_shuffle": (0, 1, 0, 0.0), "sub_octave": (0, 1, 2, 0), "sub_volume": (0, 1, 0, 0.0),
    "sub_waveform": (0, 10, 11, 2),
    "unison_1_harmonize": (0, 1, 2, 0), "unison_2_harmonize": (0, 1, 2, 0),
    "velocity_track": (-1, 1, 0, 0.0), "volume": (0, 1.4143, 0, 0.7071068),
}
for i in range(32):
    PARAMETER[f"step_seq_{i:02d}"] = (-1, 1, 0, 0.0)

# Wellenformen in Helms Reihenfolge
SIN, DREIECK, RECHTECK, SAEGE_AUF, SAEGE_AB, STUFE3, STUFE4, STUFE8, PYR3, PYR5, PYR9 = range(11)
ZUFALL_HALTEN = 11   # nur LFO: sample and hold
TEMPO = {"1/4": 7, "1/8": 8, "1/16": 9}
BPM = 100


def sek(s):
    return math.sqrt(s)


def pegel(p):
    return math.sqrt(p)


def hz(f):
    return math.log2(f)


def preset(name, beschreibung, *, o1=None, o2=None, sub=None, rauschen=0.0, fm=0.0,
           filter=None, filterhuelle=None, amp=(0.005, 1.0, 0.0, 0.5), verzerrung=None,
           delay=None, hall=None, lfo=None, modhuelle=None, anschlag=0.6, stimmen=8,
           lautstaerke=0.8, mods=(), drehung=""):
    """Baut ein Helm-Preset aus lesbaren Angaben (Sekunden, Pegel 0..1, Halbtöne)."""
    s = {k: v[3] for k, v in PARAMETER.items()}
    s["beats_per_minute"] = BPM / 60.0
    s["volume"] = pegel(lautstaerke)
    s["polyphony"] = stimmen
    s["velocity_track"] = anschlag
    s["mono_lfo_1_retrigger"] = 1
    for nr, o in ((1, o1), (2, o2)):
        o = o or {"pegel": 0.0}
        s[f"osc_{nr}_waveform"] = o.get("welle", SIN)
        s[f"osc_{nr}_volume"] = pegel(o.get("pegel", 0.5))
        s[f"osc_{nr}_transpose"] = o.get("halbtoene", 0)
        s[f"osc_{nr}_tune"] = o.get("fein", 0.0)
        s[f"osc_{nr}_unison_voices"] = o.get("unison", 1)
        s[f"osc_{nr}_unison_detune"] = o.get("verstimmung", 10.0)
    if sub:
        s["sub_waveform"] = sub.get("welle", SIN)
        s["sub_volume"] = pegel(sub["pegel"])
        s["sub_octave"] = sub.get("tiefer", 0)
    s["noise_volume"] = pegel(rauschen)
    s["cross_modulation"] = fm
    if filter:
        s["filter_on"] = 1
        s["filter_blend"] = {"tief": 0.0, "band": 1.0, "hoch": 2.0}.get(filter.get("art", "tief"), filter.get("art"))
        s["filter_style"] = 1 if filter.get("steil") else 0
        s["cutoff"] = filter["frequenz"]
        s["resonance"] = filter.get("resonanz", 0.3)
        s["keytrack"] = filter.get("keytrack", 0.0)
    if filterhuelle:
        tiefe, a, d, su, r = filterhuelle
        s.update(fil_env_depth=tiefe, fil_attack=sek(a), fil_decay=sek(d), fil_sustain=su, fil_release=sek(r))
    a, d, su, r = amp
    s.update(amp_attack=sek(a), amp_decay=sek(d), amp_sustain=su, amp_release=sek(r))
    if verzerrung:
        s.update(distortion_on=1, distortion_type=verzerrung[0], distortion_drive=verzerrung[1],
                 distortion_mix=verzerrung[2])
    if delay:
        s.update(delay_on=1, delay_sync=delay.get("sync", 1), delay_tempo=TEMPO[delay["takt"]],
                 delay_dry_wet=delay["mix"], delay_feedback=delay["rueck"])
    if hall:
        s.update(reverb_on=1, reverb_dry_wet=hall[0], reverb_feedback=hall[1], reverb_damping=hall[2])
    if lfo:
        s.update(mono_lfo_1_waveform=lfo["welle"], mono_lfo_1_sync=0, mono_lfo_1_frequency=hz(lfo["hz"]),
                 mono_lfo_1_amplitude=lfo.get("staerke", 1.0))
    if modhuelle:
        a, d, su, r = modhuelle
        s.update(mod_attack=sek(a), mod_decay=sek(d), mod_sustain=su, mod_release=sek(r))
    s["modulations"] = [{"source": q, "destination": z, "amount": m} for q, z, m in mods]
    return {"name": name, "beschreibung": beschreibung, "drehung": drehung, "settings": s}


# ---------------------------------------------------------------------------
# Die Paletten. Reihenfolge der Bälle überall gleich.
# ---------------------------------------------------------------------------

BAELLE = ["Ballon", "Medizinball", "Haar-Ball", "Softball", "Noppenball", "Tennisball"]

PALETTEN = [
    {
        "name": "Material",
        "idee": "Physisch inspiriert: Gewicht, Oberfläche und Flug des Balls bestimmen den Klang.",
        "presets": [
            preset("Ballon", "Luftharfe: gezupft, lang ausklingend, mit Atem",
                   o1={"welle": DREIECK, "pegel": 0.55}, o2={"welle": SIN, "pegel": 0.25, "halbtoene": 12},
                   rauschen=0.06, filter={"art": "tief", "frequenz": 88, "resonanz": 0.25, "keytrack": 0.5},
                   filterhuelle=(18, 0.0, 0.6, 0.0, 1.0), amp=(0.004, 3.0, 0.0, 2.2),
                   delay={"takt": "1/8", "sync": 2, "mix": 0.22, "rueck": 0.35}, hall=(0.45, 0.93, 0.3),
                   anschlag=0.5, mods=[("mod_wheel", "noise_volume", 0.45), ("mod_wheel", "cutoff", 18)],
                   drehung="mehr Wind und Helligkeit"),
            preset("Medizinball", "Erdbass: dumpfer Schlag mit tiefem Nachklang",
                   o1={"welle": SIN, "pegel": 0.8}, o2={"welle": DREIECK, "pegel": 0.1}, sub={"pegel": 0.35},
                   filter={"art": "tief", "steil": True, "frequenz": 52, "resonanz": 0.2},
                   filterhuelle=(36, 0.0, 0.18, 0.0, 0.2), amp=(0.002, 1.4, 0.2, 0.7),
                   verzerrung=(0, 8, 0.5), hall=(0.12, 0.88, 0.6), modhuelle=(0.0, 0.06, 0.0, 0.05),
                   anschlag=0.7, stimmen=4,
                   mods=[("mod_envelope", "osc_1_transpose", 12), ("mod_wheel", "cutoff", 30)],
                   drehung="Bass öffnet sich, wird knurriger"),
            preset("Haar-Ball", "Rascheln: gefiltertes Rauschen, das knistert",
                   o1={"welle": RECHTECK, "pegel": 0.06}, rauschen=0.85,
                   filter={"art": "band", "frequenz": 90, "resonanz": 0.4, "keytrack": 0.3},
                   amp=(0.03, 0.7, 0.35, 0.9), lfo={"welle": ZUFALL_HALTEN, "hz": 14}, hall=(0.3, 0.9, 0.4),
                   anschlag=0.6,
                   mods=[("mono_lfo_1", "cutoff", 20), ("random", "cutoff", 10),
                         ("mod_wheel", "mono_lfo_1_frequency", 2), ("mod_wheel", "noise_volume", 0.2)],
                   drehung="schnelleres, dichteres Knistern"),
            preset("Softball", "Weiche Marimba: rund, warm, kurz",
                   o1={"welle": SIN, "pegel": 0.72}, o2={"welle": SIN, "pegel": 0.06, "halbtoene": 24}, fm=0.04,
                   filter={"art": "tief", "frequenz": 92, "resonanz": 0.2},
                   filterhuelle=(20, 0.0, 0.2, 0.0, 0.3), amp=(0.003, 0.9, 0.0, 0.6), hall=(0.25, 0.9, 0.5),
                   anschlag=0.7, mods=[("mod_wheel", "cutoff", 16)], drehung="heller"),
            preset("Noppenball", "Rau und kratzig: verzerrte, körnige Säge",
                   o1={"welle": SAEGE_AUF, "pegel": 0.5, "unison": 5, "verstimmung": 30},
                   o2={"welle": RECHTECK, "pegel": 0.25, "halbtoene": -12},
                   filter={"art": "tief", "steil": True, "frequenz": 72, "resonanz": 0.6},
                   filterhuelle=(24, 0.0, 0.3, 0.4, 0.3), verzerrung=(1, 10, 0.7), amp=(0.008, 0.5, 0.55, 0.35),
                   lfo={"welle": ZUFALL_HALTEN, "hz": 9}, anschlag=0.5,
                   mods=[("mono_lfo_1", "osc_1_tune", 0.15), ("mod_wheel", "distortion_drive", 14),
                         ("mod_wheel", "resonance", 0.3)],
                   drehung="mehr Verzerrung und Biss"),
            preset("Tennisball", "Plopp: kurzer, heller Zupfer mit Echo",
                   o1={"welle": RECHTECK, "pegel": 0.3}, o2={"welle": SIN, "pegel": 0.12, "halbtoene": 19},
                   filter={"art": "tief", "frequenz": 70, "resonanz": 0.35},
                   filterhuelle=(55, 0.0, 0.07, 0.0, 0.1), amp=(0.001, 0.22, 0.0, 0.12),
                   modhuelle=(0.0, 0.03, 0.0, 0.03), delay={"takt": "1/16", "mix": 0.15, "rueck": 0.25},
                   anschlag=0.85, mods=[("mod_envelope", "osc_1_transpose", 7), ("mod_wheel", "resonance", 0.4)],
                   drehung="schärfer, quäkiger"),
        ],
    },
    {
        "name": "Glocken und Holz",
        "idee": "Alles wird angeschlagen: Glas, Gong, Holz, Blech. Klingt immer nach Instrument.",
        "presets": [
            preset("Ballon", "Glasharmonika: schwebend, leicht schwebend verstimmt",
                   o1={"welle": SIN, "pegel": 0.55}, o2={"welle": SIN, "pegel": 0.3, "halbtoene": 12, "fein": 0.07},
                   fm=0.12, amp=(0.25, 3.0, 0.3, 3.0), hall=(0.5, 0.95, 0.3), anschlag=0.4,
                   mods=[("mod_wheel", "cross_modulation", 0.2)], drehung="glasiger, mehr Obertöne"),
            preset("Medizinball", "Gong: tief, metallisch, sehr lang",
                   o1={"welle": SIN, "pegel": 0.8}, o2={"welle": SIN, "pegel": 0.25, "halbtoene": 5, "fein": 0.41},
                   fm=0.32, filter={"art": "tief", "frequenz": 80, "resonanz": 0.2},
                   filterhuelle=(30, 0.0, 1.2, 0.0, 1.5), amp=(0.002, 4.0, 0.0, 4.0),
                   lfo={"welle": SIN, "hz": 0.3}, hall=(0.4, 0.95, 0.4), anschlag=0.7, stimmen=4,
                   mods=[("mono_lfo_1", "osc_2_tune", 0.2), ("mod_wheel", "cross_modulation", 0.15)],
                   drehung="Gong wird schärfer"),
            preset("Haar-Ball", "Regenmacher: feines, kurzes Rieseln",
                   rauschen=0.8, filter={"art": "hoch", "frequenz": 100, "resonanz": 0.3},
                   amp=(0.01, 0.18, 0.0, 0.15), lfo={"welle": ZUFALL_HALTEN, "hz": 20}, hall=(0.25, 0.9, 0.3),
                   anschlag=0.7, stimmen=12,
                   mods=[("mono_lfo_1", "cutoff", 12), ("mod_wheel", "resonance", 0.4)],
                   drehung="pfeifender"),
            preset("Softball", "Holzblock und Marimba: trocken und kurz",
                   o1={"welle": SIN, "pegel": 0.7}, o2={"welle": DREIECK, "pegel": 0.09, "halbtoene": 12}, fm=0.06,
                   filter={"art": "tief", "frequenz": 90, "resonanz": 0.2},
                   filterhuelle=(30, 0.0, 0.08, 0.0, 0.1), amp=(0.001, 0.35, 0.0, 0.25), hall=(0.2, 0.88, 0.5),
                   anschlag=0.75, mods=[("mod_wheel", "cutoff", 18)], drehung="holziger, heller"),
            preset("Noppenball", "Blechdose: metallisch, schepprig",
                   o1={"welle": RECHTECK, "pegel": 0.6}, o2={"welle": RECHTECK, "pegel": 0.3, "halbtoene": 13, "fein": 0.3},
                   fm=0.45, filter={"art": "band", "frequenz": 80, "resonanz": 0.45}, verzerrung=(2, 6, 0.4),
                   amp=(0.001, 0.5, 0.0, 0.4), anschlag=0.6,
                   mods=[("mod_wheel", "cutoff", 20)], drehung="heller, blecherner"),
            preset("Tennisball", "Kalimba: zarter, glockiger Zupfer",
                   o1={"welle": SIN, "pegel": 0.64}, o2={"welle": SIN, "pegel": 0.09, "halbtoene": 24}, fm=0.08,
                   filter={"art": "tief", "frequenz": 100, "resonanz": 0.2},
                   filterhuelle=(10, 0.0, 0.05, 0.0, 0.1), amp=(0.001, 1.1, 0.0, 0.6),
                   delay={"takt": "1/8", "mix": 0.2, "rueck": 0.3}, anschlag=0.8,
                   mods=[("mod_wheel", "cross_modulation", 0.12)], drehung="metallischer"),
        ],
    },
    {
        "name": "Arcade",
        "idee": "8-Bit wie ein altes Videospiel: verspielt, eindeutig, sofort als Spiel erkennbar.",
        "presets": [
            preset("Ballon", "Blubber-Triller: Oktavsprünge wie ein Bonus-Sound",
                   o1={"welle": RECHTECK, "pegel": 0.25}, o2={"welle": RECHTECK, "pegel": 0.09, "halbtoene": 12},
                   lfo={"welle": RECHTECK, "hz": 12}, amp=(0.005, 1.2, 0.2, 0.5),
                   delay={"takt": "1/8", "mix": 0.3, "rueck": 0.4}, anschlag=0.4,
                   mods=[("mono_lfo_1", "osc_1_transpose", 12), ("mod_wheel", "mono_lfo_1_frequency", 2)],
                   drehung="schneller trillern"),
            preset("Medizinball", "8-Bit-Bass: stufig, kräftig",
                   o1={"welle": STUFE8, "pegel": 0.64}, sub={"welle": RECHTECK, "pegel": 0.25},
                   filter={"art": "tief", "frequenz": 70, "resonanz": 0.2}, amp=(0.002, 0.6, 0.4, 0.2),
                   modhuelle=(0.0, 0.05, 0.0, 0.05), anschlag=0.6, stimmen=4,
                   mods=[("mod_envelope", "osc_1_transpose", 12), ("mod_wheel", "cutoff", 45)],
                   drehung="Bass wird heller"),
            preset("Haar-Ball", "Computer-Plappern: zufällige Bit-Töne im Rauschen",
                   o1={"welle": STUFE3, "pegel": 0.1}, rauschen=0.5,
                   filter={"art": "hoch", "frequenz": 70, "resonanz": 0.2}, amp=(0.005, 0.4, 0.3, 0.3),
                   lfo={"welle": ZUFALL_HALTEN, "hz": 18}, anschlag=0.6,
                   mods=[("mono_lfo_1", "osc_1_transpose", 24), ("mod_wheel", "mono_lfo_1_frequency", 2)],
                   drehung="schneller plappern"),
            preset("Softball", "Pulse-Melodie: klare Spielmelodie",
                   o1={"welle": RECHTECK, "pegel": 0.49}, o2={"welle": DREIECK, "pegel": 0.09, "halbtoene": 12},
                   amp=(0.005, 0.5, 0.5, 0.2), lfo={"welle": SIN, "hz": 6, "staerke": 0.0}, anschlag=0.5,
                   mods=[("mono_lfo_1", "osc_1_tune", 0.3), ("mod_wheel", "mono_lfo_1_amplitude", 1.0)],
                   drehung="Vibrato"),
            preset("Noppenball", "Glitch: gefaltete, zerbrochene Töne",
                   o1={"welle": PYR9, "pegel": 0.49}, o2={"welle": SAEGE_AUF, "pegel": 0.16, "halbtoene": -5},
                   verzerrung=(3, 8, 0.8), amp=(0.002, 0.3, 0.3, 0.2), anschlag=0.5,
                   mods=[("mod_wheel", "distortion_drive", 12)], drehung="kaputter"),
            preset("Tennisball", "Pew: fallender Blip",
                   o1={"welle": RECHTECK, "pegel": 0.5}, amp=(0.001, 0.15, 0.0, 0.08),
                   modhuelle=(0.0, 0.12, 0.0, 0.1), delay={"takt": "1/16", "mix": 0.2, "rueck": 0.3},
                   anschlag=0.8, mods=[("mod_envelope", "osc_1_transpose", 24), ("mod_wheel", "osc_1_tune", 1.0)],
                   drehung="höher"),
        ],
    },
    {
        "name": "Wolken",
        "idee": "Abstrakt und ruhig: Flächen und Hall, nichts klingt hart. Gut für langsames Spiel.",
        "presets": [
            preset("Ballon", "Schimmerfläche: hell, weit, langsam",
                   o1={"welle": SAEGE_AUF, "pegel": 0.25, "unison": 7, "verstimmung": 20},
                   o2={"welle": SIN, "pegel": 0.16, "halbtoene": 12},
                   filter={"art": "tief", "frequenz": 78, "resonanz": 0.2}, amp=(1.2, 2.0, 0.7, 3.5),
                   lfo={"welle": SIN, "hz": 0.2}, delay={"takt": "1/4", "sync": 2, "mix": 0.25, "rueck": 0.5},
                   hall=(0.6, 0.97, 0.4), anschlag=0.3,
                   mods=[("mono_lfo_1", "cutoff", 10), ("mod_wheel", "cutoff", 24)], drehung="heller"),
            preset("Medizinball", "Drone: tiefes Brummen, das sich langsam bewegt",
                   o1={"welle": SAEGE_AUF, "pegel": 0.36, "unison": 3, "verstimmung": 8}, sub={"pegel": 0.36},
                   filter={"art": "tief", "steil": True, "frequenz": 50, "resonanz": 0.3},
                   amp=(0.8, 3.0, 0.8, 3.0), lfo={"welle": DREIECK, "hz": 0.1}, hall=(0.4, 0.95, 0.5),
                   anschlag=0.3, stimmen=4, mods=[("mono_lfo_1", "cutoff", 8), ("mod_wheel", "cutoff", 30)],
                   drehung="Drone öffnet sich"),
            preset("Haar-Ball", "Wind: pfeifendes, wanderndes Rauschen",
                   rauschen=0.95, filter={"art": "band", "frequenz": 80, "resonanz": 0.6, "keytrack": 1.0},
                   amp=(0.6, 2.0, 0.6, 2.5), lfo={"welle": SIN, "hz": 0.35}, hall=(0.5, 0.95, 0.4),
                   anschlag=0.3, mods=[("mono_lfo_1", "cutoff", 14), ("mod_wheel", "cutoff", 20)],
                   drehung="Wind wird höher"),
            preset("Softball", "Warme Fläche: weich, rund",
                   o1={"welle": DREIECK, "pegel": 0.49}, o2={"welle": SAEGE_AUF, "pegel": 0.09, "halbtoene": 12, "fein": 0.06},
                   filter={"art": "tief", "frequenz": 74, "resonanz": 0.2}, amp=(0.5, 2.0, 0.6, 2.5),
                   hall=(0.5, 0.95, 0.5), anschlag=0.3, mods=[("mod_wheel", "cutoff", 20)], drehung="heller"),
            preset("Noppenball", "Körnige Fläche: unruhig, flirrend",
                   o1={"welle": RECHTECK, "pegel": 0.36, "unison": 5, "verstimmung": 35},
                   filter={"art": "tief", "steil": True, "frequenz": 66, "resonanz": 0.5},
                   lfo={"welle": ZUFALL_HALTEN, "hz": 7}, verzerrung=(0, 6, 0.4), amp=(0.4, 2.0, 0.6, 2.0),
                   hall=(0.45, 0.95, 0.4), anschlag=0.3,
                   mods=[("mono_lfo_1", "cutoff", 14), ("mod_wheel", "mono_lfo_1_frequency", 2)],
                   drehung="mehr Flirren"),
            preset("Tennisball", "Glastropfen mit Echo",
                   o1={"welle": SIN, "pegel": 0.6}, o2={"welle": SIN, "pegel": 0.04, "halbtoene": 19}, fm=0.1,
                   amp=(0.002, 0.8, 0.0, 0.8), delay={"takt": "1/8", "sync": 2, "mix": 0.4, "rueck": 0.55},
                   hall=(0.5, 0.95, 0.4), anschlag=0.6,
                   mods=[("mod_wheel", "delay_feedback", 0.35)], drehung="längeres Echo"),
        ],
    },
    {
        "name": "Trommelkreis",
        "idee": "Rhythmus statt Melodie: jeder Ball ist eine Trommel. Passt zur Option „Rhythmus“.",
        "presets": [
            preset("Ballon", "Becken-Schwell: aufsteigendes Rauschen",
                   o1={"welle": RECHTECK, "pegel": 0.1}, o2={"welle": RECHTECK, "pegel": 0.06, "halbtoene": 7},
                   rauschen=0.36, fm=0.4, filter={"art": "hoch", "frequenz": 90, "resonanz": 0.3},
                   amp=(0.4, 1.5, 0.0, 1.8), hall=(0.5, 0.95, 0.3), anschlag=0.5,
                   mods=[("mod_wheel", "cutoff", -20)], drehung="dunkler"),
            preset("Medizinball", "Kick: Bassdrum",
                   o1={"welle": SIN, "pegel": 1.0}, amp=(0.001, 0.45, 0.0, 0.2), verzerrung=(0, 6, 0.5),
                   modhuelle=(0.0, 0.09, 0.0, 0.05), anschlag=0.8, stimmen=2,
                   mods=[("mod_envelope", "osc_1_transpose", 30), ("mod_wheel", "distortion_drive", 12)],
                   drehung="härter"),
            preset("Haar-Ball", "Shaker",
                   rauschen=0.72, filter={"art": "hoch", "frequenz": 104, "resonanz": 0.2},
                   amp=(0.015, 0.12, 0.0, 0.08), anschlag=0.8, stimmen=12,
                   mods=[("mod_wheel", "cutoff", -14)], drehung="weicher"),
            preset("Softball", "Tom",
                   o1={"welle": SIN, "pegel": 0.8}, o2={"welle": DREIECK, "pegel": 0.09}, rauschen=0.02,
                   filter={"art": "tief", "frequenz": 80, "resonanz": 0.2}, filterhuelle=(20, 0.0, 0.05, 0.0, 0.1),
                   amp=(0.001, 0.5, 0.0, 0.3), modhuelle=(0.0, 0.12, 0.0, 0.1), anschlag=0.8,
                   mods=[("mod_envelope", "osc_1_transpose", 12), ("mod_wheel", "cutoff", 20)],
                   drehung="heller"),
            preset("Noppenball", "Snare",
                   o1={"welle": DREIECK, "pegel": 0.4}, rauschen=0.8,
                   filter={"art": "hoch", "frequenz": 66, "resonanz": 0.2}, amp=(0.001, 0.22, 0.0, 0.15),
                   verzerrung=(0, 4, 0.4), modhuelle=(0.0, 0.05, 0.0, 0.05), anschlag=0.8,
                   mods=[("mod_envelope", "osc_1_transpose", 12), ("mod_wheel", "noise_volume", 0.15)],
                   drehung="mehr Teppich"),
            preset("Tennisball", "Clave: kurzer, heller Klick",
                   o1={"welle": RECHTECK, "pegel": 0.36}, o2={"welle": SIN, "pegel": 0.36, "halbtoene": 17},
                   filter={"art": "band", "frequenz": 86, "resonanz": 0.35}, amp=(0.001, 0.1, 0.0, 0.06),
                   anschlag=0.8, mods=[("mod_wheel", "cutoff", 12)], drehung="höher"),
        ],
    },
]


def pruefen(s):
    for k, v in s.items():
        if k == "modulations":
            continue
        lo, hi, schritte, _ = PARAMETER[k]
        assert lo - 1e-9 <= v <= hi + 1e-9, f"{k}={v} außerhalb {lo}..{hi}"
        if schritte:
            assert float(v).is_integer(), f"{k}={v} muss ganzzahlig sein"


def abweichungen(s):
    """Nur was vom Helm-Standard abweicht (für die Hörseite)."""
    aus = {k: round(v, 5) for k, v in s.items()
           if k != "modulations" and abs(v - PARAMETER[k][3]) > 1e-9}
    aus["modulations"] = s["modulations"]
    return aus


def helm_datei(palette, p):
    return {
        "license": "CC0: frei verwendbar.",
        "synth_version": "0.9.0",
        "patch_name": p["name"],
        "folder_name": palette["name"],
        "author": "Ball-Installation",
        "settings": p["settings"],
    }


def main():
    ordner = os.path.join(HIER, BANK)
    bank = os.path.join(HIER, BANK + ".helmbank")
    vorschau = []
    with zipfile.ZipFile(bank, "w", zipfile.ZIP_DEFLATED) as z:
        for palette in PALETTEN:
            assert [p["name"] for p in palette["presets"]] == BAELLE
            for p in palette["presets"]:
                pruefen(p["settings"])
                text = json.dumps(helm_datei(palette, p), indent=2, ensure_ascii=False)
                pfad = os.path.join(ordner, palette["name"], p["name"] + ".helm")
                os.makedirs(os.path.dirname(pfad), exist_ok=True)
                with open(pfad, "w", encoding="utf-8") as f:
                    f.write(text)
                z.writestr(f"{BANK}/{palette['name']}/{p['name']}.helm", text)
            vorschau.append({"name": palette["name"], "idee": palette["idee"], "presets": [
                {"name": p["name"], "beschreibung": p["beschreibung"], "drehung": p["drehung"],
                 "settings": abweichungen(p["settings"])} for p in palette["presets"]]})
    standard = {k: v[3] for k, v in PARAMETER.items() if not k.startswith("step_seq")}
    with open(os.path.join(HIER, "paletten.json"), "w", encoding="utf-8") as f:
        json.dump({"standard": standard, "paletten": vorschau}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(HIER, "paletten_vorlage.html"), encoding="utf-8") as f:
        seite = f.read()
    daten = json.dumps({"standard": standard, "paletten": vorschau}, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(HIER, "paletten.html"), "w", encoding="utf-8") as f:
        f.write(seite.replace("/*DATEN*/null", daten.replace("</", "<\\/")))
    print(f"{sum(len(p['presets']) for p in PALETTEN)} Presets → {ordner}")
    print(f"Bank → {bank}")


if __name__ == "__main__":
    main()
