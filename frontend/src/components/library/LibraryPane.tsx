import { useState } from "react";
import { LuImageOff, LuPencil, LuTrash2 } from "react-icons/lu";
import type { ProjectSummary } from "../../lib/library/snapshot";
import StackLabel from "../core/StackLabel";
import { Button, buttonVariants } from "../ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "../ui/alert-dialog";

interface LibraryPaneProps {
  available: boolean;
  projects: ProjectSummary[];
  currentProjectId: string | null;
  // Switching projects mid-generation isn't allowed (the request is still writing to the open one).
  isGenerating: boolean;
  onOpen: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onDelete: (id: string) => void;
}

function editedAgo(timestamp: number, now: number = Date.now()): string {
  const minutes = Math.round((now - timestamp) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  if (hours < 48) return "yesterday";
  return new Date(timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function ProjectName({ project, onRename }: { project: ProjectSummary; onRename: (name: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(project.name);

  if (!editing) {
    return (
      <button
        type="button"
        data-testid="library-name"
        className="group flex min-w-0 items-center gap-1.5 text-left text-sm font-medium text-gray-900 dark:text-gray-100"
        title="Rename"
        onClick={() => {
          setDraft(project.name);
          setEditing(true);
        }}
      >
        <span className="truncate">{project.name}</span>
        <LuPencil className="h-3 w-3 shrink-0 text-gray-400 opacity-0 group-hover:opacity-100" />
      </button>
    );
  }
  const finish = (save: boolean) => {
    setEditing(false);
    if (save && draft.trim() && draft.trim() !== project.name) onRename(draft.trim());
  };
  return (
    <input
      data-testid="library-rename-input"
      autoFocus
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => finish(true)}
      onKeyDown={(event) => {
        if (event.key === "Enter") finish(true);
        if (event.key === "Escape") finish(false);
      }}
      className="w-full rounded border border-gray-300 bg-white px-1.5 py-0.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
    />
  );
}

function LibraryPane({
  available,
  projects,
  currentProjectId,
  isGenerating,
  onOpen,
  onRename,
  onDelete,
}: LibraryPaneProps) {
  return (
    <div data-testid="library-pane" className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-4 lg:px-6 lg:py-6">
        <div className="mb-6">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Library</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            Every project is saved automatically, in this browser. Clearing the site's data or switching browsers
            loses them, so download anything you want to keep.
          </p>
        </div>

        {!available && (
          <p className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
            This browser isn't letting the app store projects (a private window, or site storage turned off), so
            projects aren't being saved.
          </p>
        )}

        {available && projects.length === 0 && (
          <p className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500 dark:border-zinc-700 dark:text-gray-400">
            No saved projects yet. Generate something and it will show up here.
          </p>
        )}

        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => {
            const isCurrent = project.id === currentProjectId;
            return (
              <li
                key={project.id}
                data-testid="library-item"
                data-project-id={project.id}
                className={`flex flex-col overflow-hidden rounded-xl border bg-white dark:bg-zinc-900 ${
                  isCurrent ? "border-violet-400 dark:border-violet-500" : "border-gray-200 dark:border-zinc-800"
                }`}
              >
                <div className="flex h-44 items-start justify-center overflow-hidden bg-gray-100 dark:bg-zinc-800">
                  {project.thumbnail ? (
                    <img src={project.thumbnail} alt="" className="w-full object-cover object-top" />
                  ) : (
                    <LuImageOff className="mt-16 h-8 w-8 text-gray-300 dark:text-zinc-600" />
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-2 p-3">
                  <ProjectName project={project} onRename={(name) => onRename(project.id, name)} />
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
                    <StackLabel stack={project.stack} />
                    <span>
                      {project.versionCount} {project.versionCount === 1 ? "version" : "versions"}
                    </span>
                    <span>Edited {editedAgo(project.updatedAt)}</span>
                  </div>
                  <div className="mt-auto flex items-center gap-2 pt-1">
                    <Button
                      size="sm"
                      data-testid="library-open"
                      disabled={isGenerating && !isCurrent}
                      title={isGenerating && !isCurrent ? "Wait for the current generation to finish" : undefined}
                      onClick={() => onOpen(project.id)}
                    >
                      {isCurrent ? "Back to project" : "Open"}
                    </Button>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button size="sm" variant="ghost" data-testid="library-delete" title="Delete">
                          <LuTrash2 className="h-4 w-4" />
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Delete “{project.name}”?</AlertDialogTitle>
                          <AlertDialogDescription>
                            This removes the project and all its versions from this browser. It can't be undone.
                            {isCurrent && " It's the open project, so you'll start a new one."}
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            data-testid="library-confirm-delete"
                            className={buttonVariants({ variant: "destructive" })}
                            onClick={() => onDelete(project.id)}
                          >
                            Delete
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

export default LibraryPane;
