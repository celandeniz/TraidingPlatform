import { BacktestRunner } from "@/components/core/backtest/backtest-runner";
import { EquityCurve } from "@/components/core/backtest/equity-curve";
import { GreeksCalc } from "@/components/core/backtest/greeks-calc";
import { RegimeSelect } from "@/components/core/backtest/regime-select";
import { ScenariosGrid } from "@/components/core/backtest/scenarios-grid";
import { WalkForward } from "@/components/core/backtest/walk-forward";
import { PageTitle } from "@/components/shell/page-title";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS = [
  { v: "backtest", label: "Backtest", el: <BacktestRunner /> },
  { v: "walkforward", label: "Walk-Forward", el: <WalkForward /> },
  { v: "scenarios", label: "Scenarios", el: <ScenariosGrid /> },
  { v: "select", label: "Regime Select", el: <RegimeSelect /> },
  { v: "equity", label: "Equity", el: <EquityCurve /> },
  { v: "greeks", label: "Greeks", el: <GreeksCalc /> },
];

export default function BacktestPage() {
  return (
    <>
      <PageTitle
        title="Backtest & Validation"
        description="Backtest runner, walk-forward, saved scenarios, regime selection, equity curve, and an offline options-greeks calculator."
      />
      <Tabs defaultValue="backtest">
        <TabsList className="flex flex-wrap">
          {TABS.map((t) => <TabsTrigger key={t.v} value={t.v}>{t.label}</TabsTrigger>)}
        </TabsList>
        {TABS.map((t) => <TabsContent key={t.v} value={t.v}>{t.el}</TabsContent>)}
      </Tabs>
    </>
  );
}
