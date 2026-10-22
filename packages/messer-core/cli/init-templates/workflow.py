"""{{name}} — Messer workflow created with `messer create`. Each step is a function (or an agent); steps run as
soon as their inputs are ready. Run it locally with `messer start` and publish it with `messer push`."""

from messer import Workflow


def saludar(nombre: str = "mundo") -> str:
    return f"Hola, {nombre}"


workflow = Workflow(name="{{name}}").step(saludar)
