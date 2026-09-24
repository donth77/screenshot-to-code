import { useState } from "react";
import toast from "react-hot-toast";
import { LuDownload } from "react-icons/lu";
import { SNACK_EXPORT_ENABLED } from "../../../config";
import { useExpoSdk } from "../../../lib/react-native/appRuntime";
import { ReactNativeDevice } from "../../../lib/react-native/devices";
import {
  MAX_SNACK_URL_LENGTH,
  snackSdkVersion,
  snackUrl,
  usesLocalAssets,
} from "../../../lib/react-native/snack";
import { Button } from "../../ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "../../ui/popover";
import { downloadExpoProject, downloadReactNativePreview } from "../download";

interface Props {
  code: string;
  device: ReactNativeDevice;
}

function MenuItem({
  title,
  detail,
  onClick,
  testId,
}: {
  title: string;
  detail: string;
  onClick: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className="flex w-full flex-col items-start rounded-md px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-zinc-800"
    >
      <span className="text-sm font-medium text-gray-900 dark:text-zinc-100">{title}</span>
      <span className="text-xs text-gray-500 dark:text-zinc-400">{detail}</span>
    </button>
  );
}

// React Native exports: the Expo project, the offline preview page, and
// (behind VITE_SNACK_EXPORT) Snack.
function ReactNativeExportMenu({ code, device }: Props) {
  const [open, setOpen] = useState(false);
  const { value: sdk } = useExpoSdk(open);
  const sdkMajor = sdk?.sdk.split(".")[0];
  const snackSdk = sdk ? snackSdkVersion(sdk)?.split(".")[0] : undefined;

  const run = async (action: () => Promise<void>, failure: string) => {
    setOpen(false);
    try {
      await action();
    } catch (error) {
      console.error(failure, error);
      toast.error(`${failure} Is the backend running?`);
    }
  };

  const downloadProject = () =>
    run(() => downloadExpoProject(code), "Couldn't export the Expo project.");

  const downloadPreview = () =>
    run(async () => {
      const { missingImages } = await downloadReactNativePreview(code, device);
      if (missingImages.length > 0) {
        toast(
          `${missingImages.length} image${missingImages.length === 1 ? "" : "s"} couldn't be embedded and will load from the network.`
        );
      }
    }, "Couldn't build the preview HTML.");

  const openSnack = () => {
    setOpen(false);
    if (!sdk) return;
    const url = snackUrl(code, sdk);
    if (url.length > MAX_SNACK_URL_LENGTH) {
      toast.error("App.jsx is too long to send to Snack. Download the Expo project instead.");
      return;
    }
    if (usesLocalAssets(code)) {
      toast("Snack can't load this app's local images; they'll be missing there.");
    }
    window.open(url, "_blank", "noopener");
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          title="Export"
          className="h-9 w-9"
          data-testid="rn-export-menu"
        >
          <LuDownload />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-1">
        <MenuItem
          title="Download Expo project"
          detail={`A .zip to run with Expo Go${sdkMajor ? ` (SDK ${sdkMajor})` : ""} or build`}
          onClick={downloadProject}
          testId="download-expo-project"
        />
        <MenuItem
          title="Download preview HTML"
          detail="One file that opens offline in a browser"
          onClick={downloadPreview}
          testId="download-preview-html"
        />
        {SNACK_EXPORT_ENABLED && snackSdk && (
          <MenuItem
            title="Open in Snack"
            detail={`Opens in Snack (Expo SDK ${snackSdk})`}
            onClick={openSnack}
            testId="open-in-snack"
          />
        )}
      </PopoverContent>
    </Popover>
  );
}

export default ReactNativeExportMenu;
