"""
Modelo del data center - v2
Cambio: factor_hotspot ahora es PARAMETRO, no constante global.
"""
import random

P_IDLE = 50
P_MAX = 400
EXPONENTE = 3
BOOT_TICKS = 3
BOOT_WATTS = 400
TICKS = 240
N_GPUS = 5
N_TAREAS = 60


class GPU:
    def __init__(self, id, idle_timeout, factor_hotspot):
        self.id = id
        self.idle_timeout = idle_timeout
        self.factor_hotspot = factor_hotspot
        self.estado = "off"
        self.boot_restante = 0
        self.idle_desde = None
        self.tareas = []

    @property
    def carga(self):
        return sum(w.demanda for w in self.tareas)

    def disponible(self):
        return self.estado == "on"

    def potencia(self):
        if self.estado == "off":
            return 0.0
        if self.estado == "booting":
            return BOOT_WATTS
        return P_IDLE + (P_MAX - P_IDLE) * self.carga

    def potencia_cooling(self):
        if self.estado == "off":
            return 0.0
        return self.potencia() * (
            1 + self.factor_hotspot * self.carga ** EXPONENTE)

    def encender(self):
        if self.estado == "off":
            self.estado = "booting"
            self.boot_restante = BOOT_TICKS

    def tick(self, t):
        if self.estado == "booting":
            self.boot_restante -= 1
            if self.boot_restante <= 0:
                self.estado = "on"
                self.idle_desde = t
        elif self.estado == "on":
            if self.tareas:
                self.idle_desde = None
            else:
                if self.idle_desde is None:
                    self.idle_desde = t
                elif t - self.idle_desde >= self.idle_timeout:
                    self.estado = "off"
                    self.idle_desde = None


class Workload:
    def __init__(self, id, llegada, duracion, demanda):
        self.id = id
        self.llegada = llegada
        self.duracion = duracion
        self.demanda = demanda
        self.restante = duracion
        self.inicio = None

    def espera(self):
        return None if self.inicio is None else self.inicio - self.llegada


def elegir_spread(gpus, w):
    c = [g for g in gpus if g.disponible() and g.carga + w.demanda <= 1.0]
    return min(c, key=lambda g: g.carga) if c else None


def elegir_consolidar(gpus, w):
    c = [g for g in gpus if g.disponible() and g.carga + w.demanda <= 1.0]
    return max(c, key=lambda g: g.carga) if c else None


def simular(elegir_gpu, workloads, idle_timeout, factor_hotspot):
    gpus = [GPU(i, idle_timeout, factor_hotspot) for i in range(N_GPUS)]
    gpus[0].estado = "on"
    pendientes = sorted(workloads, key=lambda w: w.llegada)
    cola = []
    energia_it = 0.0
    energia_cool = 0.0
    encendidos = 0

    for t in range(TICKS):
        while pendientes and pendientes[0].llegada == t:
            cola.append(pendientes.pop(0))

        sin_lugar = []
        for w in cola:
            g = elegir_gpu(gpus, w)
            if g:
                g.tareas.append(w)
                w.inicio = t
            else:
                sin_lugar.append(w)
        cola = sin_lugar

        if cola:
            apagadas = [g for g in gpus if g.estado == "off"]
            if apagadas:
                apagadas[0].encender()
                encendidos += 1

        energia_it += sum(g.potencia() for g in gpus) / 60 / 1000
        energia_cool += sum(g.potencia_cooling() - g.potencia()
                            for g in gpus) / 60 / 1000

        for g in gpus:
            for w in list(g.tareas):
                w.restante -= 1
                if w.restante <= 0:
                    g.tareas.remove(w)
            g.tick(t)

    iniciadas = [w for w in workloads if w.inicio is not None]
    esperas = sorted(w.espera() for w in iniciadas)
    sin_iniciar = len(workloads) - len(iniciadas)

    def percentil(datos, p):
        if not datos:
            return 0
        i = min(int(p * len(datos)), len(datos) - 1)
        return datos[i]

    return {
        "total": energia_it + energia_cool,
        "it": energia_it,
        "cool": energia_cool,
        "encendidos": encendidos,
        # --- latencia ---
        # OJO: prom/p95/max solo cuentan las tareas que ARRANCARON.
        # Sin mirar sin_iniciar, un scheduler que mata tareas parece rapido.
        "espera_prom": sum(esperas) / len(esperas) if esperas else 0,
        "espera_p95": percentil(esperas, 0.95),
        "espera_max": esperas[-1] if esperas else 0,
        "sin_iniciar": sin_iniciar,
        "pct_atendidas": len(iniciadas) / len(workloads) * 100,
    }


def generar_workloads(semilla):
    rng = random.Random(semilla)
    return [Workload(
        id=i,
        llegada=rng.randint(0, TICKS - 40),
        duracion=rng.randint(10, 40),
        demanda=round(rng.uniform(0.1, 0.6), 2),
    ) for i in range(N_TAREAS)]


def generar_workloads_ondas(semilla, amplitud=1.0, ciclos=2):
    """Como generar_workloads, pero las llegadas se concentran en picos.

    amplitud = 0.0 -> llegadas parejas (control)
    amplitud = 1.0 -> picos y valles marcados
    ciclos         -> cuantas olas entran en la simulacion
    """
    import math
    rng = random.Random(semilla)
    ventana = TICKS - 40

    # Peso de cada minuto: una onda que sube y baja.
    pesos = [1 + amplitud * math.sin(2 * math.pi * ciclos * t / ventana)
             for t in range(ventana)]
    pesos = [max(p, 0.01) for p in pesos]      # nunca negativo

    llegadas = rng.choices(range(ventana), weights=pesos, k=N_TAREAS)

    return [Workload(
        id=i,
        llegada=llegadas[i],
        duracion=rng.randint(10, 40),
        demanda=round(rng.uniform(0.1, 0.6), 2),
    ) for i in range(N_TAREAS)]
