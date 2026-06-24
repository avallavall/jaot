"""
Generator registry — maps generator type strings to generator classes.

Usage:
    from app.domains.solver.services.generators import get_generator
    gen = get_generator("assignment")
    problem = gen.generate(user_input, params)
"""

from app.domains.solver.services.generators.assignment import AssignmentGenerator
from app.domains.solver.services.generators.base import (
    BaseGenerator,
    GeneratorRegistry,
    GenericGenerator,
)
from app.domains.solver.services.generators.bin_packing import BinPackingGenerator
from app.domains.solver.services.generators.blending import BlendingGenerator
from app.domains.solver.services.generators.cash_flow import CashFlowGenerator
from app.domains.solver.services.generators.covering import CoveringGenerator
from app.domains.solver.services.generators.crop_rotation import CropRotationGenerator
from app.domains.solver.services.generators.cutting_stock import CuttingStockGenerator
from app.domains.solver.services.generators.energy_storage import EnergyStorageGenerator
from app.domains.solver.services.generators.facility_location import FacilityLocationGenerator
from app.domains.solver.services.generators.fleet_sizing import FleetSizingGenerator
from app.domains.solver.services.generators.irrigation import IrrigationGenerator
from app.domains.solver.services.generators.knapsack import KnapsackGenerator
from app.domains.solver.services.generators.lot_sizing import LotSizingGenerator
from app.domains.solver.services.generators.markdown_pricing import MarkdownPricingGenerator
from app.domains.solver.services.generators.mdpdp import MDPDPGenerator
from app.domains.solver.services.generators.network_flow import NetworkFlowGenerator
from app.domains.solver.services.generators.portfolio import PortfolioGenerator
from app.domains.solver.services.generators.procurement import ProcurementGenerator
from app.domains.solver.services.generators.production import (
    BudgetAllocationGenerator,
    ProductionGenerator,
)
from app.domains.solver.services.generators.quality_control import QualityControlGenerator
from app.domains.solver.services.generators.renewable import RenewableCurtailmentGenerator
from app.domains.solver.services.generators.routing import RoutingGenerator
from app.domains.solver.services.generators.scheduling import SchedulingGenerator
from app.domains.solver.services.generators.set_cover import SetCoverGenerator
from app.domains.solver.services.generators.spanning_tree import SpanningTreeGenerator
from app.domains.solver.services.generators.strip_packing import StripPackingGenerator

# Register all generators
GeneratorRegistry.register("assignment", AssignmentGenerator)
GeneratorRegistry.register("scheduling", SchedulingGenerator)
GeneratorRegistry.register("employee_scheduling", SchedulingGenerator)
GeneratorRegistry.register("routing", RoutingGenerator)
GeneratorRegistry.register("vehicle_routing", RoutingGenerator)
GeneratorRegistry.register("blending", BlendingGenerator)
GeneratorRegistry.register("fertilizer", BlendingGenerator)
GeneratorRegistry.register("knapsack", KnapsackGenerator)
GeneratorRegistry.register("production", ProductionGenerator)
GeneratorRegistry.register("budget_allocation", BudgetAllocationGenerator)
GeneratorRegistry.register("portfolio", PortfolioGenerator)
GeneratorRegistry.register("bin_packing", BinPackingGenerator)
GeneratorRegistry.register("covering", CoveringGenerator)
GeneratorRegistry.register("network_flow", NetworkFlowGenerator)
GeneratorRegistry.register("facility_location", FacilityLocationGenerator)
GeneratorRegistry.register("cutting_stock", CuttingStockGenerator)
GeneratorRegistry.register("set_cover", SetCoverGenerator)
GeneratorRegistry.register("lot_sizing", LotSizingGenerator)
GeneratorRegistry.register("fleet_sizing", FleetSizingGenerator)
GeneratorRegistry.register("procurement", ProcurementGenerator)
GeneratorRegistry.register("cash_flow", CashFlowGenerator)
GeneratorRegistry.register("energy_storage", EnergyStorageGenerator)
GeneratorRegistry.register("crop_rotation", CropRotationGenerator)
GeneratorRegistry.register("irrigation", IrrigationGenerator)
GeneratorRegistry.register("renewable_curtailment", RenewableCurtailmentGenerator)
GeneratorRegistry.register("quality_control", QualityControlGenerator)
GeneratorRegistry.register("markdown_pricing", MarkdownPricingGenerator)
GeneratorRegistry.register("strip_packing", StripPackingGenerator)
GeneratorRegistry.register("spanning_tree", SpanningTreeGenerator)
GeneratorRegistry.register("mdpdp", MDPDPGenerator)
GeneratorRegistry.register("generic", GenericGenerator)

# Public API
GENERATOR_REGISTRY = GeneratorRegistry


def get_generator(name: str) -> BaseGenerator:
    """Get a generator instance by name. Falls back to GenericGenerator for unknown types."""
    return GeneratorRegistry.get(name)


__all__ = [
    "BaseGenerator",
    "GenericGenerator",
    "GeneratorRegistry",
    "GENERATOR_REGISTRY",
    "get_generator",
    "AssignmentGenerator",
    "BinPackingGenerator",
    "BlendingGenerator",
    "BudgetAllocationGenerator",
    "CashFlowGenerator",
    "CoveringGenerator",
    "CropRotationGenerator",
    "CuttingStockGenerator",
    "EnergyStorageGenerator",
    "FacilityLocationGenerator",
    "FleetSizingGenerator",
    "IrrigationGenerator",
    "KnapsackGenerator",
    "LotSizingGenerator",
    "MDPDPGenerator",
    "MarkdownPricingGenerator",
    "NetworkFlowGenerator",
    "PortfolioGenerator",
    "ProcurementGenerator",
    "ProductionGenerator",
    "QualityControlGenerator",
    "RenewableCurtailmentGenerator",
    "RoutingGenerator",
    "SchedulingGenerator",
    "SetCoverGenerator",
    "SpanningTreeGenerator",
    "StripPackingGenerator",
]
