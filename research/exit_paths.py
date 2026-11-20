"""Independent hypothetical exit paths. Overlap, sizing and funding settle in chronological order."""

import numpy as np


def prefix_max(values, lib):
    if lib is np:
        return np.maximum.accumulate(values, axis=1)
    out = values.copy()
    stride = 1
    while stride < values.shape[1]:
        out[:, stride:] = lib.maximum(out[:, stride:], out[:, :-stride])
        stride *= 2
    return out


def exit_paths(frame, config, lib=np, batch_size=512):
    sides = frame["signal"].to_numpy()
    candidates = np.flatnonzero((sides[:-1] == "LONG") | (sides[:-1] == "SHORT"))
    if not len(candidates):
        return {}
    horizon = min(int(config["time_stop"]), len(frame))
    if horizon < 1 or batch_size < 1:
        raise ValueError("Time stop and batch size must be positive")
    if lib is not np:
        free, _ = lib.cuda.runtime.memGetInfo()
        batch_size = max(1, min(batch_size, free // (horizon * 512)))
    opens, highs, lows, closes, atr = [
        lib.asarray(frame[k].to_numpy(dtype=float)) for k in ("open", "high", "low", "close", "atr")
    ]
    stops = np.where(sides == "LONG", frame["long_stop"], frame["short_stop"])
    results = {}
    offsets = lib.arange(horizon)[None, :]
    for start in range(0, len(candidates), batch_size):
        sig = candidates[start : start + batch_size]
        entries = lib.asarray(sig + 1)[:, None]
        direction = lib.asarray(np.where(sides[sig] == "LONG", 1.0, -1.0))[:, None]
        idx = lib.minimum(entries + offsets, len(frame) - 1)
        entry = opens[entries]
        stop = lib.asarray(stops[sig])[:, None]
        distance = (entry - stop) * direction
        target = entry + direction * config["target_r"] * distance
        # Orient both sides so a larger price always favours the position.
        favourable = lib.where(direction > 0, highs[idx], -lows[idx])
        adverse = lib.where(direction > 0, lows[idx], -highs[idx])
        best = prefix_max(lib.maximum(favourable, entry * direction), lib)
        initial = stop * direction
        proposed = best - config["chandelier_atr"] * atr[idx]
        proposed = lib.where(lib.isfinite(atr[idx]) & (atr[idx] > 0), proposed, initial)
        trail = prefix_max(lib.maximum(proposed, initial), lib)
        active = lib.concatenate((initial, trail[:, :-1]), axis=1)
        op = opens[idx] * direction
        goal = target * direction
        gap_stop, gap_target = op <= active, op >= goal
        stop_hit, target_hit = adverse <= active, favourable >= goal
        final = (entries + offsets >= len(frame) - 1) | (offsets == horizon - 1)
        hit = gap_stop | gap_target | stop_hit | target_hit | final
        last = lib.argmax(hit, axis=1)
        row = lib.arange(len(sig))

        def at(x):
            return x[row, last]

        reason = lib.where(
            gap_stop,
            0,
            lib.where(
                gap_target,
                1,
                lib.where(
                    stop_hit & target_hit,
                    2,
                    lib.where(
                        stop_hit,
                        lib.where(active == initial, 3, 4),
                        lib.where(
                            target_hit, 5, lib.where(offsets == int(config["time_stop"]) - 1, 6, 7)
                        ),
                    ),
                ),
            ),
        )
        fill = lib.where(
            gap_stop,
            op,
            lib.where(
                gap_target,
                goal,
                lib.where(stop_hit, active, lib.where(target_hit, goal, closes[idx] * direction)),
            ),
        )
        prior = offsets < last[:, None]
        base = entry * direction
        mae = lib.min(lib.where(prior, adverse, base), axis=1)
        mfe = lib.max(lib.where(prior, favourable, base), axis=1)
        r = at(reason)
        # A non-triggering time/data-end candle contributes its entire range.
        mae = lib.minimum(
            mae,
            lib.where(r >= 6, at(adverse), lib.where((r == 1) | (r == 5), base[:, 0], at(fill))),
        )
        mfe = lib.maximum(
            mfe,
            lib.where(
                r >= 6,
                at(favourable),
                lib.where((r == 0) | (r == 1) | (r == 5), at(fill), base[:, 0]),
            ),
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            record = lib.stack(
                (
                    at(idx),
                    at(fill) * direction[:, 0],
                    r,
                    at(active) * direction[:, 0],
                    (mae - base[:, 0]) / distance[:, 0],
                    (mfe - base[:, 0]) / distance[:, 0],
                ),
                axis=1,
            )
        results.update(zip(sig.tolist(), record if lib is np else lib.asnumpy(record)))
    return results


def pullback_windows(frame, config, lib, chunk_size):
    """Compute completed lookback windows with an overlap of N preceding bars."""
    n = int(config["pullback_n"])
    long_pb = np.zeros(len(frame), dtype=bool)
    short_pb = np.zeros(len(frame), dtype=bool)
    long_stop = np.full(len(frame), np.nan)
    short_stop = np.full(len(frame), np.nan)
    for start in range(n, len(frame), chunk_size):
        end = min(len(frame), start + chunk_size)
        lo, hi, close, fast, mid, atr = [
            lib.asarray(frame[name].to_numpy()[start - n : end])
            for name in ("low", "high", "close", "ema_fast", "ema_mid", "atr")
        ]

        def windows(values):
            return lib.lib.stride_tricks.sliding_window_view(values, n + 1)

        touch_long = windows(lo <= fast)[:, :-1].any(axis=1)
        touch_short = windows(hi >= fast)[:, :-1].any(axis=1)
        distance = config["pullback_depth_atr"] * atr
        broken_long = windows(close < mid - distance)[:, :-1].any(axis=1)
        broken_short = windows(close > mid + distance)[:, :-1].any(axis=1)
        buffer = config["stop_buffer_atr"] * atr[n:]
        for dest, values in (
            (long_pb, touch_long & ~broken_long),
            (short_pb, touch_short & ~broken_short),
            (long_stop, windows(lo).min(axis=1) - buffer),
            (short_stop, windows(hi).max(axis=1) + buffer),
        ):
            dest[start:end] = values if lib is np else lib.asnumpy(values)
    return long_pb, short_pb, long_stop, short_stop
