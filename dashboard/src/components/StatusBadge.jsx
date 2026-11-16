const KIND = {
  Pending: "pending",
  Confirmed: "confirmed",
  Rejected: "rejected",
  "Action Taken": "done",
  Reopened: "pending",
  "Plate corrected": "rejected",
};

export default function StatusBadge({ status }) {
  return <span className={`badge ${KIND[status] || "pending"}`}>{status}</span>;
}
