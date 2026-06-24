export interface GuideMetadata {
  title: string;
  description: string;
  slug: string;
  category: string;
  difficulty: "beginner" | "intermediate" | "advanced";
  domain: string;
  templateCount: number;
  templateIds: string[];
}

/**
 * Domain clusters mapping ~10 domain names to arrays of ModelCategory values.
 * Every one of the 34 categories appears in exactly one cluster.
 */
export const DOMAIN_CLUSTERS: Record<string, string[]> = {
  Manufacturing: [
    "manufacturing",
    "cutting_packing",
    "food_beverage",
    "textile",
    "chemical_engineering",
    "construction",
  ],
  Finance: ["finance", "insurance", "real_estate"],
  Logistics: [
    "logistics",
    "transportation",
    "maritime",
    "railway",
    "facility_location",
    "warehouse",
  ],
  "Supply Chain": ["supply_chain"],
  "Energy & Environment": ["energy", "environmental", "water_management"],
  "Healthcare & Pharma": ["healthcare", "pharmaceutical"],
  Technology: ["telecom", "network_graph", "advertising_media"],
  Services: ["retail", "hr", "sports", "education"],
  "Natural Resources": ["agriculture", "mining", "forestry"],
  "Public Sector": ["government", "aerospace"],
  General: ["general"],
};

/**
 * All 34 guide entries, one per ModelCategory value.
 */
export const guides: GuideMetadata[] = [
  // Manufacturing
  {
    title: "Production Planning",
    description: "Optimize manufacturing schedules to maximize throughput and minimize costs",
    slug: "production-planning",
    category: "manufacturing",
    difficulty: "intermediate",
    domain: "Manufacturing",
    templateCount: 4,
    templateIds: ["production_planning", "job_shop_scheduling", "quality_control_sampling", "raw_material_purchasing"],
  },
  {
    title: "Cutting & Packing",
    description: "Minimize material waste with optimal cutting patterns and bin packing",
    slug: "cutting-and-packing",
    category: "cutting_packing",
    difficulty: "advanced",
    domain: "Manufacturing",
    templateCount: 3,
    templateIds: ["one_d_cutting_stock", "two_d_cutting", "strip_packing"],
  },
  {
    title: "Food & Beverage Production",
    description: "Plan recipes, batches, and production runs for food manufacturing",
    slug: "food-and-beverage",
    category: "food_beverage",
    difficulty: "intermediate",
    domain: "Manufacturing",
    templateCount: 3,
    templateIds: ["recipe_optimization", "production_line_scheduling", "ingredient_sourcing"],
  },
  {
    title: "Textile Manufacturing",
    description: "Optimize fabric cutting, dyeing schedules, and production lines",
    slug: "textile-manufacturing",
    category: "textile",
    difficulty: "intermediate",
    domain: "Manufacturing",
    templateCount: 2,
    templateIds: ["fabric_cutting", "dye_batch_scheduling"],
  },
  {
    title: "Chemical Process Optimization",
    description: "Balance reactor yields, blending ratios, and process constraints",
    slug: "chemical-process",
    category: "chemical_engineering",
    difficulty: "advanced",
    domain: "Manufacturing",
    templateCount: 3,
    templateIds: ["reactor_optimization", "chemical_blending", "pipeline_network_flow"],
  },
  {
    title: "Construction Project Planning",
    description: "Schedule tasks, allocate crews, and manage resources across job sites",
    slug: "construction-planning",
    category: "construction",
    difficulty: "intermediate",
    domain: "Manufacturing",
    templateCount: 3,
    templateIds: ["project_scheduling", "equipment_allocation", "material_procurement"],
  },

  // Finance
  {
    title: "Portfolio Optimization",
    description: "Allocate investments to maximize returns under risk constraints",
    slug: "portfolio-optimization",
    category: "finance",
    difficulty: "intermediate",
    domain: "Finance",
    templateCount: 5,
    templateIds: ["budget_allocation", "portfolio_optimization", "cash_flow_planning", "loan_portfolio", "revenue_maximization"],
  },
  {
    title: "Insurance Risk Modeling",
    description: "Optimize policy pricing and claims reserve allocation",
    slug: "insurance-risk",
    category: "insurance",
    difficulty: "advanced",
    domain: "Finance",
    templateCount: 2,
    templateIds: ["risk_pool_optimization", "claims_adjuster_assignment"],
  },
  {
    title: "Real Estate Investment",
    description: "Evaluate property portfolios and optimize acquisition strategies",
    slug: "real-estate-investment",
    category: "real_estate",
    difficulty: "intermediate",
    domain: "Finance",
    templateCount: 3,
    templateIds: ["property_portfolio", "renovation_scheduling", "tenant_mix_optimization"],
  },

  // Logistics
  {
    title: "Route & Fleet Optimization",
    description: "Plan delivery routes and fleet assignments to reduce costs and time",
    slug: "route-and-fleet",
    category: "logistics",
    difficulty: "intermediate",
    domain: "Logistics",
    templateCount: 5,
    templateIds: ["knapsack", "vehicle_routing", "bin_packing", "warehouse_layout", "fleet_sizing"],
  },
  {
    title: "Transportation Network Design",
    description: "Design freight networks balancing speed, cost, and capacity",
    slug: "transportation-network",
    category: "transportation",
    difficulty: "advanced",
    domain: "Logistics",
    templateCount: 3,
    templateIds: ["transportation_problem", "transshipment", "multi_modal_freight"],
  },
  {
    title: "Maritime Shipping",
    description: "Optimize vessel routing, port scheduling, and cargo allocation",
    slug: "maritime-shipping",
    category: "maritime",
    difficulty: "advanced",
    domain: "Logistics",
    templateCount: 3,
    templateIds: ["vessel_scheduling", "container_loading", "port_berth_allocation"],
  },
  {
    title: "Railway Operations",
    description: "Schedule trains, allocate rolling stock, and manage track capacity",
    slug: "railway-operations",
    category: "railway",
    difficulty: "advanced",
    domain: "Logistics",
    templateCount: 3,
    templateIds: ["train_timetabling", "rolling_stock_assignment", "track_maintenance_scheduling"],
  },
  {
    title: "Facility Location",
    description: "Choose optimal locations for warehouses, plants, and service centers",
    slug: "facility-location",
    category: "facility_location",
    difficulty: "intermediate",
    domain: "Logistics",
    templateCount: 3,
    templateIds: ["warehouse_location", "service_center_placement", "capacitated_facility_location"],
  },
  {
    title: "Warehouse Layout & Operations",
    description: "Optimize storage layouts, picking routes, and inventory placement",
    slug: "warehouse-operations",
    category: "warehouse",
    difficulty: "intermediate",
    domain: "Logistics",
    templateCount: 3,
    templateIds: ["warehouse_slotting", "pick_route_optimization", "inventory_replenishment"],
  },

  // Supply Chain
  {
    title: "Supply Chain Planning",
    description: "Coordinate procurement, production, and distribution across the value chain",
    slug: "supply-chain-planning",
    category: "supply_chain",
    difficulty: "advanced",
    domain: "Supply Chain",
    templateCount: 3,
    templateIds: ["inventory_optimization", "supplier_selection", "demand_allocation"],
  },

  // Energy & Environment
  {
    title: "Energy Grid Optimization",
    description: "Balance power generation, storage, and distribution for efficiency",
    slug: "energy-grid",
    category: "energy",
    difficulty: "advanced",
    domain: "Energy & Environment",
    templateCount: 3,
    templateIds: ["power_generation_mix", "energy_storage_dispatch", "renewable_curtailment"],
  },
  {
    title: "Environmental Resource Management",
    description: "Optimize emissions reduction, waste processing, and sustainability targets",
    slug: "environmental-management",
    category: "environmental",
    difficulty: "intermediate",
    domain: "Energy & Environment",
    templateCount: 2,
    templateIds: ["waste_collection_routing", "emission_reduction_planning"],
  },
  {
    title: "Water Distribution Networks",
    description: "Design and manage water supply, treatment, and distribution systems",
    slug: "water-distribution",
    category: "water_management",
    difficulty: "intermediate",
    domain: "Energy & Environment",
    templateCount: 3,
    templateIds: ["water_distribution_network", "reservoir_operation", "wastewater_treatment_allocation"],
  },

  // Healthcare & Pharma
  {
    title: "Healthcare Resource Allocation",
    description: "Schedule staff, beds, and equipment to improve patient outcomes",
    slug: "healthcare-resources",
    category: "healthcare",
    difficulty: "intermediate",
    domain: "Healthcare & Pharma",
    templateCount: 3,
    templateIds: ["diet_optimization", "nurse_scheduling", "operating_room_scheduling"],
  },
  {
    title: "Pharmaceutical Production",
    description: "Plan drug manufacturing, batch scheduling, and quality compliance",
    slug: "pharmaceutical-production",
    category: "pharmaceutical",
    difficulty: "advanced",
    domain: "Healthcare & Pharma",
    templateCount: 3,
    templateIds: ["drug_trial_scheduling", "production_batch_planning", "drug_distribution"],
  },

  // Technology
  {
    title: "Telecom Network Planning",
    description: "Optimize tower placement, bandwidth allocation, and coverage areas",
    slug: "telecom-network",
    category: "telecom",
    difficulty: "advanced",
    domain: "Technology",
    templateCount: 3,
    templateIds: ["cell_tower_placement", "bandwidth_allocation", "network_redundancy"],
  },
  {
    title: "Network & Graph Optimization",
    description: "Solve shortest path, flow, and connectivity problems on graphs",
    slug: "network-graph",
    category: "network_graph",
    difficulty: "intermediate",
    domain: "Technology",
    templateCount: 3,
    templateIds: ["shortest_path", "minimum_spanning_tree", "max_flow"],
  },
  {
    title: "Advertising & Media Planning",
    description: "Allocate ad budgets across channels to maximize reach and conversions",
    slug: "advertising-media",
    category: "advertising_media",
    difficulty: "beginner",
    domain: "Technology",
    templateCount: 2,
    templateIds: ["ad_campaign_budget", "media_mix_optimization"],
  },

  // Services
  {
    title: "Retail Assortment & Pricing",
    description: "Optimize product mix, shelf placement, and pricing strategies",
    slug: "retail-assortment",
    category: "retail",
    difficulty: "beginner",
    domain: "Services",
    templateCount: 3,
    templateIds: ["store_layout", "markdown_pricing", "assortment_planning"],
  },
  {
    title: "Workforce Scheduling",
    description: "Build shift schedules that balance coverage, fairness, and labor costs",
    slug: "workforce-scheduling",
    category: "hr",
    difficulty: "intermediate",
    domain: "Services",
    templateCount: 3,
    templateIds: ["employee_scheduling", "workforce_assignment", "training_program_selection"],
  },
  {
    title: "Sports League Scheduling",
    description: "Create balanced fixture lists with venue, travel, and broadcast constraints",
    slug: "sports-scheduling",
    category: "sports",
    difficulty: "beginner",
    domain: "Services",
    templateCount: 2,
    templateIds: ["tournament_scheduling", "team_roster_optimization"],
  },
  {
    title: "Education Timetabling",
    description: "Schedule classes, rooms, and instructors to avoid conflicts",
    slug: "education-timetabling",
    category: "education",
    difficulty: "intermediate",
    domain: "Services",
    templateCount: 2,
    templateIds: ["course_scheduling", "student_assignment"],
  },

  // Natural Resources
  {
    title: "Agricultural Planning",
    description: "Optimize crop rotation, planting schedules, and resource allocation",
    slug: "agricultural-planning",
    category: "agriculture",
    difficulty: "beginner",
    domain: "Natural Resources",
    templateCount: 3,
    templateIds: ["fertilizer_mixing", "crop_rotation", "irrigation_scheduling"],
  },
  {
    title: "Mining Operations",
    description: "Plan extraction sequences, equipment deployment, and processing flows",
    slug: "mining-operations",
    category: "mining",
    difficulty: "advanced",
    domain: "Natural Resources",
    templateCount: 3,
    templateIds: ["mine_production_scheduling", "ore_blending", "fleet_dispatch_mining"],
  },
  {
    title: "Forestry Management",
    description: "Schedule harvesting, replanting, and sustainable yield planning",
    slug: "forestry-management",
    category: "forestry",
    difficulty: "intermediate",
    domain: "Natural Resources",
    templateCount: 3,
    templateIds: ["harvest_scheduling", "timber_transportation", "wildfire_resource_deployment"],
  },

  // Public Sector
  {
    title: "Government Resource Allocation",
    description: "Distribute public budgets and resources across departments and regions",
    slug: "government-resources",
    category: "government",
    difficulty: "beginner",
    domain: "Public Sector",
    templateCount: 3,
    templateIds: ["public_facility_location", "emergency_response_allocation", "public_budget_allocation"],
  },
  {
    title: "Aerospace Mission Planning",
    description: "Optimize flight paths, payload distribution, and mission scheduling",
    slug: "aerospace-mission",
    category: "aerospace",
    difficulty: "advanced",
    domain: "Public Sector",
    templateCount: 3,
    templateIds: ["satellite_scheduling", "flight_crew_pairing", "launch_vehicle_payload"],
  },

  // General
  {
    title: "Getting Started with Optimization",
    description: "Learn the fundamentals of mathematical optimization with simple examples",
    slug: "getting-started-optimization",
    category: "general",
    difficulty: "beginner",
    domain: "General",
    templateCount: 3,
    templateIds: ["custom", "multi_objective_demo", "constraint_satisfaction_demo"],
  },
];

/**
 * Guides grouped by domain cluster, preserving domain cluster order.
 */
export const guidesByDomain: Record<string, GuideMetadata[]> = (() => {
  const result: Record<string, GuideMetadata[]> = {};
  for (const domain of Object.keys(DOMAIN_CLUSTERS)) {
    const domainGuides = guides.filter((g) => g.domain === domain);
    if (domainGuides.length > 0) {
      result[domain] = domainGuides;
    }
  }
  return result;
})();
