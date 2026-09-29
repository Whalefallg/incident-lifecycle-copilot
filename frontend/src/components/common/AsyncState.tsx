interface AsyncStateProps {
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function AsyncState({ title, description, action }: AsyncStateProps) {
  return (
    <section className="async-state" role="status">
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </section>
  );
}
