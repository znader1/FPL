import { useState } from "react";
import { Sliders } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer";
import { ParameterForm, type ParameterFormProps } from "./ParameterForm";

/** Floating settings button + bottom drawer for < lg screens. */
export const MobileParameterDrawer = (props: ParameterFormProps) => {
  const [open, setOpen] = useState(false);

  return (
    <Drawer open={open} onOpenChange={setOpen}>
      <DrawerTrigger asChild>
        <Button
          size="icon"
          className="lg:hidden fixed bottom-5 right-5 z-40 h-12 w-12 rounded-full shadow-lg bg-primary text-white hover:bg-primary/90"
          aria-label="Open squad parameters"
        >
          <Sliders className="h-5 w-5" />
        </Button>
      </DrawerTrigger>
      <DrawerContent className="max-h-[85vh]">
        <DrawerHeader className="pb-0">
          <DrawerTitle className="text-sm font-bold tracking-tight">Parameters</DrawerTitle>
        </DrawerHeader>
        <div className="overflow-y-auto">
          <ParameterForm
            {...props}
            onRecommend={() => {
              setOpen(false);
              props.onRecommend();
            }}
          />
        </div>
      </DrawerContent>
    </Drawer>
  );
};
