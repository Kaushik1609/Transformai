/**
 * TransformIQ — Create Transformation page.
 *
 * The Stitch-style guided creation console: Input Workspace → Configure →
 * Output Packages → Review & Dispatch, executing a real transformation job
 * under the quick project.
 */
import { AppShell } from "@/components/layout/AppShell";
import { CreateTransformationWorkflow } from "@/components/workspace/CreateTransformationWorkflow";

export default function CreateTransformationPage() {
  return (
    <AppShell>
      <CreateTransformationWorkflow />
    </AppShell>
  );
}