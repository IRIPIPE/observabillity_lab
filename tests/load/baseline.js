import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 2,
  duration: '30s',

  thresholds: {
    checks: ['rate==1'],
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

export default function () {
  const response = http.get('http://api:8000/tasks');

  check(response, {
    'status is 200': (r) => r.status === 200,
  });

  sleep(0.5);
}
