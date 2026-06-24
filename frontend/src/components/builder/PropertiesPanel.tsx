"use client";

import { useBuilderStore } from "@/hooks/useBuilderStore";
import { useShallow } from "zustand/react/shallow";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  VariableNodeData,
  ConstraintNodeData,
  ObjectiveNodeData,
} from "@/lib/builder/types";
import { useTranslations } from "next-intl";

function VariableProperties({
  data,
  onUpdate,
}: {
  data: VariableNodeData;
  onUpdate: (patch: Partial<VariableNodeData>) => void;
}) {
  const t = useTranslations("builder");
  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs text-muted-foreground">{t("properties.name")}</Label>
        <Input
          value={data.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
          className="mt-1 font-mono"
          placeholder={t("properties.variablePlaceholder")}
        />
      </div>

      <div>
        <Label className="text-xs text-muted-foreground">{t("properties.type")}</Label>
        <Select
          value={data.type}
          onValueChange={(v) => onUpdate({ type: v as VariableNodeData["type"] })}
        >
          <SelectTrigger className="mt-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="continuous">{t("properties.continuous")}</SelectItem>
            <SelectItem value="integer">{t("properties.integer")}</SelectItem>
            <SelectItem value="binary">{t("properties.binary")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {data.type !== "binary" && (
        <>
          <div>
            <Label className="text-xs text-muted-foreground">{t("properties.lowerBound")}</Label>
            <Input
              type="number"
              value={data.lower_bound ?? ""}
              onChange={(e) =>
                onUpdate({
                  lower_bound: e.target.value === "" ? null : parseFloat(e.target.value),
                })
              }
              className="mt-1 font-mono"
              placeholder={t("properties.nonePlaceholder")}
            />
          </div>

          <div>
            <Label className="text-xs text-muted-foreground">{t("properties.upperBound")}</Label>
            <Input
              type="number"
              value={data.upper_bound ?? ""}
              onChange={(e) =>
                onUpdate({
                  upper_bound: e.target.value === "" ? null : parseFloat(e.target.value),
                })
              }
              className="mt-1 font-mono"
              placeholder={t("properties.nonePlaceholder")}
            />
          </div>
        </>
      )}
    </div>
  );
}

function ConstraintProperties({
  data,
  onUpdate,
}: {
  data: ConstraintNodeData;
  onUpdate: (patch: Partial<ConstraintNodeData>) => void;
}) {
  const t = useTranslations("builder");
  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs text-muted-foreground">{t("properties.name")}</Label>
        <Input
          value={data.name}
          onChange={(e) => onUpdate({ name: e.target.value })}
          className="mt-1"
          placeholder={t("properties.constraintPlaceholder")}
        />
      </div>

      <div>
        <Label className="text-xs text-muted-foreground">{t("properties.operator")}</Label>
        <Select
          value={data.operator}
          onValueChange={(v) => onUpdate({ operator: v as ConstraintNodeData["operator"] })}
        >
          <SelectTrigger className="mt-1 font-mono">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="<=">{t("properties.lte")}</SelectItem>
            <SelectItem value=">=">{t("properties.gte")}</SelectItem>
            <SelectItem value="==">{t("properties.eq")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs text-muted-foreground">{t("properties.rhs")}</Label>
        <Input
          type="number"
          value={data.rhs}
          onChange={(e) => onUpdate({ rhs: parseFloat(e.target.value) || 0 })}
          className="mt-1 font-mono"
        />
      </div>
    </div>
  );
}

function ObjectiveProperties({
  data,
  onUpdate,
}: {
  data: ObjectiveNodeData;
  onUpdate: (patch: Partial<ObjectiveNodeData>) => void;
}) {
  const t = useTranslations("builder");
  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs text-muted-foreground">{t("properties.sense")}</Label>
        <Select
          value={data.sense}
          onValueChange={(v) => onUpdate({ sense: v as ObjectiveNodeData["sense"] })}
        >
          <SelectTrigger className="mt-1">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="minimize">{t("properties.minimize")}</SelectItem>
            <SelectItem value="maximize">{t("properties.maximize")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="p-3 bg-muted/30 rounded text-xs text-muted-foreground">
        {t("properties.objectiveHint")}
      </div>
    </div>
  );
}

export function PropertiesPanel() {
  const t = useTranslations("builder");
  const { selectedNodeId, nodes, updateNodeData } = useBuilderStore(useShallow((s) => ({
    selectedNodeId: s.selectedNodeId,
    nodes: s.nodes,
    updateNodeData: s.updateNodeData,
  })));

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);

  if (!selectedNode) return <div className="w-72 border-l" />;

  const handleUpdate = (patch: object) => {
    updateNodeData(selectedNode.id, patch as Parameters<typeof updateNodeData>[1]);
  };

  return (
    <div className="w-72 border-l bg-background flex flex-col shrink-0">
      <div className="px-4 py-3 border-b">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {t("properties.title")}
        </p>
        <p className="text-sm font-medium text-foreground mt-0.5 capitalize">
          {t("properties.nodeLabel", { type: selectedNode.type })}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {selectedNode.type === "variable" && (
          <VariableProperties
            data={selectedNode.data as VariableNodeData}
            onUpdate={handleUpdate}
          />
        )}
        {selectedNode.type === "constraint" && (
          <ConstraintProperties
            data={selectedNode.data as ConstraintNodeData}
            onUpdate={handleUpdate}
          />
        )}
        {selectedNode.type === "objective" && (
          <ObjectiveProperties
            data={selectedNode.data as ObjectiveNodeData}
            onUpdate={handleUpdate}
          />
        )}
      </div>
    </div>
  );
}
