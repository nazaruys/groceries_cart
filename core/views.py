from django.contrib.auth import get_user_model, authenticate, login, logout
from rest_framework import generics, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework import mixins
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from groups.signals import reset_group_admin_signal
from groups.models import Group
from .serializers import UserSerializer, LoginSerializer
from .functions import is_valid_password
from .permissions import IsUsersProfile


User = get_user_model()


class UserViewSet(mixins.CreateModelMixin,
                   mixins.RetrieveModelMixin,
                   mixins.UpdateModelMixin,
                   mixins.ListModelMixin,
                   GenericViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.request.user and self.request.user.is_staff:
            self.permission_classes = [AllowAny]
        else:
            if self.action == 'list':
                permission_classes = [IsAdminUser]
            elif self.action == 'retrieve':
                permission_classes = [IsUsersProfile]
            elif self.action == 'update':
                permission_classes = [IsUsersProfile]
            elif self.action == 'create':
                permission_classes = [AllowAny]
            else:
                permission_classes = [IsAuthenticated]
        return super().get_permissions()

        
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        errors = {}
        password = request.data['password']
        if not is_valid_password(password):
            errors['password'] = 'Password must be at least 8 characters long and have at least one number, capital and lower letter.'
        group_id = request.data.get('group_id')
        if group_id and not Group.objects.filter(code=group_id).exists():
            errors['group'] = 'Group does not exist.'
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_create(serializer)

        user = serializer.instance
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)

        response_data = {
            'user': serializer.data,
            'token': {
                'refresh': str(refresh),
                'access': access_token,
            }
        }

        headers = self.get_success_headers(serializer.data)
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        errors = {}
        password = request.data.get('password')
        if password and not is_valid_password(password):
            errors['password'] = 'Password must be at least 8 characters long and have at least one number, capital and lower letter.'
        group_id = request.data.get('group_id')
        if group_id and not Group.objects.filter(code=group_id).exists():
            errors['group_id'] = 'Group does not exist.'
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        if instance.group_id and group_id != instance.group_id:
            previous_group_admin = Group.objects.get(code=instance.group_id).admin
            # If user is an admin of previous group:
            if instance == previous_group_admin:
                reset_group_admin_signal.send(sender=User, instance=instance)
        
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class LoginView(APIView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        user = authenticate(request, username=username, password=password)

        if user is not None:
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token)
            })
        
        return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)
    
class LogoutView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh_token')
            if not refresh_token:
                return Response({'detail': "No refresh token provided."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                token = RefreshToken(refresh_token)
            except TokenError:
                return Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
            token.blacklist()
            return Response({'detail': "Successfully logged out."}, status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response({'detail': "An unexpected error occured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)