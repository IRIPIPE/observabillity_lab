import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-arrival-rate',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 20,

      stages: [
        { duration: '30s', target: 5 },
        { duration: '10s', target: 30 },
        { duration: '1m', target: 30 },
        { duration: '10s', target: 5 },
        { duration: '30s', target: 5 },
      ],
    },
  },

  thresholds: {
    checks: ['rate==1'],
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    dropped_iterations: ['count==0'],
  },
};

export default function () {
  const response = http.get('http://api:8000/tasks');

  check(response, {
    'status is 200': (r) => r.status === 200,
  });
}
