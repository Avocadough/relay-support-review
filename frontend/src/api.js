export async function api(path, body) {
  const options =
    body === undefined
      ? {}
      : {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        };
  const response = await fetch(`/api${path}`, options);
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      'The server returned an unreadable response. Check the local service and try again.',
    );
  }
  if (!response.ok) {
    const detail =
      typeof data.detail === 'string'
        ? data.detail
        : 'The request could not be completed. Check the entered values.';
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return data;
}
