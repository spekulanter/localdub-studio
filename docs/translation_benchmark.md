# EN→SK translation benchmark

Characters per second: 14.0

## Summary

| Model | Total s | Avg s/segment | Over budget | Errors |
| --- | ---: | ---: | ---: | --- |
| qwen3:8b | 127.89 | 10.66 | 4 | — |
| translategemma:4b | 47.30 | 3.94 | 8 | — |

## Segment results

| # | Time | EN source | Budget | qwen3:8b (SK) | translategemma:4b (SK) | Human rating (1-5) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.00–2.00 | Mira called before the show. | 28 | Mira volala pred show. (22) | Mira zavolala pred začiatkom predstavenia. **OVER (42)** |  |
| 2 | 2.05–4.30 | She said she was nervous. | 31 | Hovorila, že je nervózna. (25) | Povedala, že je nervózna. (25) |  |
| 3 | 4.35–6.30 | Tell her to break a leg! | 27 | Pozdravuj ju a želaj šťastie! **OVER (29)** | Požiň ju, aby mala veľa šťastia! **OVER (32)** |  |
| 4 | 6.35–7.50 | It's raining cats and dogs. | 16 | Pršie ako z krygu. **OVER (18)** | Dážď pada veľmi silne. **OVER (22)** |  |
| 5 | 7.55–9.00 | I left my umbrella at home. | 20 | Zabudol som si kryg. (20) | Zabudol som si zobrať dáždnik. **OVER (30)** |  |
| 6 | 9.05–10.50 | No problem, Alex has a spare. | 20 | Alex má rezervu. (16) | Nič, Alex má náhradnú časť. **OVER (27)** |  |
| 7 | 10.55–12.40 | The train leaves at 8:15. | 25 | Trať odchádza o 8:15. (21) | Vlak odchádza o 8:15. (21) |  |
| 8 | 12.45–14.20 | Are we still meeting at the station? | 24 | Stíhaš sa ešte na stanici? **OVER (26)** | Stále sa stretávame na stanici? **OVER (31)** |  |
| 9 | 14.25–15.20 | Absolutely. | 13 | Absolútne. (10) | Samozrejme. (11) |  |
| 10 | 15.25–17.20 | Don't let the cat out of the bag. | 27 | Nech si mačku v košíku. (23) | Neodhaluj to. (13) |  |
| 11 | 17.25–19.40 | I promise I won't say a word. | 30 | Zaručujem, že nič nevyznie. (27) | Zaručujem, že nebudem nič povedať. **OVER (34)** |  |
| 12 | 19.45–26.45 | When the lights go out, follow the blue line through the garden and wait beside the old stone fountain until the music starts. | 98 | Keď sa svetlo vypne, sleduj modrú čiaru cez sady a čakaj vedľa starého kamenného fontánu, kým začne hudba. **OVER (106)** | Keď zhasnú svetlá, postupujte pozdĺž modrej značky cez záhradu a počkajte pri starom kamennom fontáne, kým sa nezačne hudba. **OVER (124)** |  |

## Per-segment latency

| Model | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3:8b | 120.25 | 1.86 | 0.50 | 0.41 | 0.42 | 0.81 | 0.54 | 0.48 | 0.31 | 0.45 | 0.52 | 1.27 |
| translategemma:4b | 43.46 | 0.28 | 0.32 | 0.21 | 0.36 | 0.32 | 0.32 | 0.27 | 0.20 | 0.23 | 0.36 | 0.81 |
