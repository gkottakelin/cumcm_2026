from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

OUT_DIR = Path("out")

x = np.linspace(0, 10, 100)
y = np.sin(x)

fig, ax = plt.subplots()
ax.plot(x, y, label=r"$\sin(x)$")

ax.set_xlabel("时间 (s)")
ax.set_ylabel("振幅")
ax.legend()

fig.savefig(OUT_DIR / "example.pdf")
plt.close()
