import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../../api/client";

function formValue(values: FormData, name: string): string {
  const value = values.get(name);
  return typeof value === "string" ? value : "";
}

export function CreateIncidentForm() {
  const [isOpen, setIsOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: api.createIncident,
    onSuccess: async (incident) => {
      await queryClient.invalidateQueries({ queryKey: ["incidents"] });
      await navigate(`/incidents/${encodeURIComponent(incident.incident_id)}`);
    },
  });

  if (!isOpen) {
    return <button type="button" onClick={() => setIsOpen(true)}>New demo incident</button>;
  }

  return (
    <form
      className="create-form"
      onSubmit={(event) => {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        mutation.mutate({
          title: formValue(values, "title"),
          service: formValue(values, "service"),
          severity: formValue(values, "severity"),
          description: formValue(values, "description"),
        });
      }}
    >
      <label>Title<input name="title" defaultValue="Checkout API elevated errors" required /></label>
      <label>Service<input name="service" defaultValue="checkout-service" required /></label>
      <label>Severity
        <select name="severity" defaultValue="P0">
          <option>P0</option><option>P1</option><option>P2</option><option>P3</option>
        </select>
      </label>
      <label>Description<textarea name="description" defaultValue="Error rate reached 8%" /></label>
      {mutation.isError ? (
        <p className="form-error" role="alert">
          {mutation.error instanceof ApiError ? mutation.error.message : "Unable to create incident"}
        </p>
      ) : null}
      <div className="form-actions">
        <button type="button" className="button-secondary" onClick={() => setIsOpen(false)}>Cancel</button>
        <button type="submit" disabled={mutation.isPending}>{mutation.isPending ? "Creating…" : "Create incident"}</button>
      </div>
    </form>
  );
}
