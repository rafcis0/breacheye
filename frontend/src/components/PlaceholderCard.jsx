
export default function PlaceholderCard({ label, ticket }) {
  return (
    <div className="placeholder-card">
      <div className="placeholder-card__label">{label}</div>
      {ticket && (
        <div className="placeholder-card__ticket">#{ticket}</div>
      )}
    </div>
  )
}
