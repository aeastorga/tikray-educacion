"""Prueba de carga de la portería: N marcaciones repartidas en M minutos desde varias porterías.

    python -m app.carga --colegio demo                      # 1000 marcaciones en 10 minutos
    python -m app.carga --colegio demo --rapido             # las mismas, sin esperar (lo antes posible)
    python -m app.carga --colegio demo --total 300 --minutos 2 --porterias 2

Entra como la portería (por defecto la de la demo), baja el padrón como lo haría el celular y
envía cada marcación por separado (una lectura de QR = una petición, como en línea). Mide el
tiempo de respuesta en el cliente y termina con código 1 si hubo errores o si el p95 pasa de
300 ms, que es la regla del proyecto. Úsala contra el colegio demo, nunca contra uno real: deja
marcaciones de verdad (se borran con `python -m app.cli demo <subdominio>`).

Para 1000 alumnos distintos: `python -m app.cli demo demo --alumnos-por-seccion 40`.
Necesita httpx (requirements-dev.txt).
"""

import argparse
import random
import statistics
import sys
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

import httpx

LIMITE_MS = 300


@dataclass
class Resultado:
    latencias_ms: list[float] = field(default_factory=list)
    resultados: Counter = field(default_factory=Counter)
    errores: list[str] = field(default_factory=list)
    duracion_s: float = 0.0

    def percentil(self, p: float) -> float:
        if not self.latencias_ms:
            return 0.0
        orden = sorted(self.latencias_ms)
        return orden[min(len(orden) - 1, round(p / 100 * (len(orden) - 1)))]

    @property
    def aprobada(self) -> bool:
        return not self.errores and self.percentil(95) <= LIMITE_MS

    def informe(self) -> str:
        n = len(self.latencias_ms)
        if not n:
            return "Sin marcaciones enviadas."
        lineas = [
            f"Marcaciones: {n} en {self.duracion_s:.1f} s ({n / self.duracion_s:.1f} por segundo)",
            f"Tiempo de respuesta (ms): p50 {self.percentil(50):.0f} · p95 {self.percentil(95):.0f} · "
            f"p99 {self.percentil(99):.0f} · máx {max(self.latencias_ms):.0f} · "
            f"promedio {statistics.fmean(self.latencias_ms):.0f}",
            "Resultados: " + ", ".join(f"{k} {v}" for k, v in self.resultados.most_common()),
            f"Errores: {len(self.errores)}" + (f" (primero: {self.errores[0]})" if self.errores else ""),
            f"Regla p95 ≤ {LIMITE_MS} ms y sin errores: {'CUMPLE' if self.aprobada else 'NO CUMPLE'}",
        ]
        return "\n".join(lineas)


def ingresar(cliente: httpx.Client, cabeceras: dict, usuario: str, clave: str) -> dict:
    r = cliente.post("/api/auth/ingreso", json={"usuario": usuario, "clave": clave}, headers=cabeceras)
    r.raise_for_status()
    return {**cabeceras, "Authorization": f"Bearer {r.json()['token']}"}


def codigos(cliente: httpx.Client, cabeceras: dict) -> list[str]:
    r = cliente.get("/api/asistencia/porteria", headers=cabeceras)
    r.raise_for_status()
    return [a["codigo"] for a in r.json()["alumnos"] if a["codigo"]]


def ejecutar(cliente: httpx.Client, cabeceras: dict, lista: list[str], total: int = 1000, segundos: float = 600,
             porterias: int = 4, semilla: int = 1) -> Resultado:
    """Reparte `total` lecturas entre `porterias` hilos. Cada portería tiene su horario (llegadas al
    azar dentro de la ventana, como en la puerta) y espera a que toque cada una. Si hay menos
    alumnos que lecturas, los códigos se repiten (segunda lectura: duplicado o salida)."""
    rnd = random.Random(semilla)
    orden = rnd.sample(lista, len(lista))
    lecturas = [orden[i % len(orden)] for i in range(total)]
    horas = sorted(rnd.uniform(0, segundos) for _ in range(total)) if segundos > 0 else [0.0] * total
    res, candado = Resultado(), threading.Lock()
    inicio = time.monotonic()

    def porteria(n: int) -> None:
        for i in range(n, total, porterias):
            espera = inicio + horas[i] - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            cuerpo = {"marcaciones": [{"id_cliente": f"carga-{uuid.uuid4().hex}", "codigo": lecturas[i],
                                       "equipo": f"carga-{n + 1}"}]}
            t0 = time.perf_counter()
            try:
                r = cliente.post("/api/asistencia/marcaciones", json=cuerpo, headers=cabeceras)
                ms = (time.perf_counter() - t0) * 1000
                if r.status_code != 200:
                    error, resultado = f"HTTP {r.status_code}: {r.text[:120]}", "error"
                else:
                    item = r.json()["resultados"][0]
                    resultado = item.get("resultado") or item.get("estado", "?")
                    error = item.get("mensaje") if item.get("estado") == "error" else None
            except httpx.HTTPError as e:
                ms, error, resultado = (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {e}", "error"
            with candado:
                res.latencias_ms.append(ms)
                res.resultados[resultado] += 1
                if error:
                    res.errores.append(error)

    hilos = [threading.Thread(target=porteria, args=(n,), daemon=True) for n in range(porterias)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    res.duracion_s = time.monotonic() - inicio
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.carga", description="Prueba de carga de la portería")
    p.add_argument("--url", default="http://localhost:8000", help="dirección del backend")
    p.add_argument("--colegio", default="demo", help="subdominio del colegio (demo)")
    p.add_argument("--dominio", default="localhost", help="DOMINIO_BASE del backend")
    p.add_argument("--usuario", default="90000004", help="usuario de portería (el de la demo)")
    p.add_argument("--clave", default="Demo2026Tikray")
    p.add_argument("--total", type=int, default=1000)
    p.add_argument("--minutos", type=float, default=10)
    p.add_argument("--porterias", type=int, default=4)
    p.add_argument("--rapido", action="store_true", help="sin esperas: todas las marcaciones lo antes posible")
    a = p.parse_args(argv)

    host = {"Host": f"{a.colegio}.{a.dominio}"}
    with httpx.Client(base_url=a.url, timeout=10, limits=httpx.Limits(max_connections=a.porterias + 2)) as cliente:
        cabeceras = ingresar(cliente, host, a.usuario, a.clave)
        lista = codigos(cliente, cabeceras)
        if not lista:
            print("El colegio no tiene alumnos con carnet.", file=sys.stderr)
            return 2
        segundos = 0 if a.rapido else a.minutos * 60
        print(f"{a.total} marcaciones, {len(lista)} alumnos distintos, {a.porterias} porterías, "
              f"{'sin esperas' if a.rapido else f'{a.minutos:g} minutos'}…", flush=True)
        res = ejecutar(cliente, cabeceras, lista, a.total, segundos, a.porterias)
    print(res.informe())
    return 0 if res.aprobada else 1


if __name__ == "__main__":
    sys.exit(main())
